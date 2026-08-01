#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winhttp.h>
#include <shlobj.h>
#include <SimConnect.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "SimConnect.lib")

namespace {
std::atomic_bool g_quit{false};
HANDLE g_sim{};
std::ofstream g_log;
std::string g_log_path;
std::string g_status_path;
std::string g_target_url;
bool g_release_latched=false;
std::string g_one_shot_camera_sig;
std::atomic<double> g_camera_get_x{0.0}, g_camera_get_y{0.0}, g_camera_get_z{0.0};
std::chrono::steady_clock::time_point g_camera_get_at{}, g_camera_status_at{};

std::string now_iso(){SYSTEMTIME st{};GetSystemTime(&st);char b[64];std::snprintf(b,sizeof(b),"%04u-%02u-%02uT%02u:%02u:%02uZ",st.wYear,st.wMonth,st.wDay,st.wHour,st.wMinute,st.wSecond);return b;}
std::wstring widen(const std::string& s){if(s.empty())return{};int n=MultiByteToWideChar(CP_UTF8,0,s.c_str(),-1,nullptr,0);std::wstring w(n?size_t(n):0,L'\0');if(n)MultiByteToWideChar(CP_UTF8,0,s.c_str(),-1,w.data(),n);if(!w.empty()&&w.back()==L'\0')w.pop_back();return w;}
std::string narrow(const std::wstring& w){if(w.empty())return{};int n=WideCharToMultiByte(CP_UTF8,0,w.c_str(),-1,nullptr,0,nullptr,nullptr);std::string s(n?size_t(n):0,'\0');if(n)WideCharToMultiByte(CP_UTF8,0,w.c_str(),-1,s.data(),n,nullptr,nullptr);if(!s.empty()&&s.back()=='\0')s.pop_back();return s;}
std::string env_or(const char* name,const std::string& fallback){char buf[32768];DWORD n=GetEnvironmentVariableA(name,buf,sizeof(buf));return n>0&&n<sizeof(buf)?std::string(buf,n):fallback;}
std::string local_appdata(){PWSTR p=nullptr;std::string out=".";if(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData,0,nullptr,&p))&&p){out=narrow(p);CoTaskMemFree(p);}return out;}
void ensure_parent(const std::string& path){auto w=widen(path);auto pos=w.find_last_of(L"\\/");if(pos!=std::wstring::npos){std::wstring dir=w.substr(0,pos);SHCreateDirectoryExW(nullptr,dir.c_str(),nullptr);}}
std::string json_escape(const std::string& s){std::string o;for(char c:s){switch(c){case'\\':o+="\\\\";break;case'\"':o+="\\\"";break;case'\n':o+="\\n";break;case'\r':break;case'\t':o+="\\t";break;default:o+=c;}}return o;}
void log(const std::string& m){if(!g_log.is_open()){ensure_parent(g_log_path);g_log.open(g_log_path,std::ios::app);}if(g_log.is_open()){g_log<<"["<<now_iso()<<"] "<<m<<"\n";g_log.flush();}}
bool ok(HRESULT hr){return SUCCEEDED(hr);}
std::string hr(HRESULT x){std::ostringstream s;s<<"0x"<<std::hex<<std::uppercase<<static_cast<unsigned long>(x);return s.str();}

std::string trim(std::string s){auto ns=[](unsigned char c){return !std::isspace(c);};s.erase(s.begin(),std::find_if(s.begin(),s.end(),ns));s.erase(std::find_if(s.rbegin(),s.rend(),ns).base(),s.end());return s;}
std::string upper(std::string s){std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return char(std::toupper(c));});return s;}

struct CameraView{std::string mode="tail_follow";double distance=45.0,height=9.0,side=0.0,pitch=-7.0,orbit=180.0,smoothing=0.35;};
struct BoardTarget{std::string callsign,airport,tab,command;std::optional<double> lat,lon,alt,object_id;bool released=false;CameraView view;bool valid()const{return released||object_id.has_value()||!callsign.empty();}};
struct Aircraft{DWORD object_id{};std::string atc_id,airline,flight,title;double lat{},lon{},alt{},hdg{},pitch{},bank{},vx{},vy{},vz{};};

void status(const std::string& state,const std::string& message,const std::string& target="",const std::string& match="", bool running=true,const CameraView* view=nullptr){
    ensure_parent(g_status_path);
    std::ofstream f(g_status_path,std::ios::trunc);
    if(!f)return;
    CameraView fallback;
    const CameraView& v=view?*view:fallback;
    f<<"{\n"
     <<"  \"updated_at\": \""<<now_iso()<<"\",\n"
     <<"  \"running\": "<<(running?"true":"false")<<",\n"
     <<"  \"state\": \""<<json_escape(state)<<"\",\n"
     <<"  \"message\": \""<<json_escape(message)<<"\",\n"
     <<"  \"target\": \""<<json_escape(target)<<"\",\n"
     <<"  \"match\": \""<<json_escape(match)<<"\",\n"
     <<"  \"mode\": \""<<json_escape(v.mode)<<"\",\n"
      <<"  \"distance\": "<<v.distance<<",\n"
      <<"  \"height\": "<<v.height<<",\n"
      <<"  \"sideOffset\": "<<v.side<<",\n"
      <<"  \"pitch\": "<<v.pitch<<",\n"
      <<"  \"orbitAngle\": "<<v.orbit<<",\n"
      <<"  \"smoothing\": "<<v.smoothing<<",\n"
      <<"  \"cameraPosX\": "<<g_camera_get_x.load()<<",\n"
      <<"  \"cameraPosY\": "<<g_camera_get_y.load()<<",\n"
      <<"  \"cameraPosZ\": "<<g_camera_get_z.load()<<"\n"
      <<"}";
}

#pragma pack(push,8)
struct AircraftWire{char atc_id[32];char airline[32];char flight[32];char title[128];double lat,lon,alt,hdg,pitch,bank,vx,vy,vz;};
#pragma pack(pop)

std::string safe(const char* d,size_t n){size_t i=0;while(i<n&&d[i])++i;return std::string(d,i);}
std::string norm(std::string v){std::string o;for(unsigned char c:v)if(std::isalnum(c))o.push_back(char(std::toupper(c)));return o;}

double dist_m(double a,double b,double c,double d){constexpr double R=6371008.8,k=0.01745329251994329577;double a1=a*k,a2=c*k,dx=(c-a)*k,dy=(d-b)*k;double h=std::sin(dx/2)*std::sin(dx/2)+std::cos(a1)*std::cos(a2)*std::sin(dy/2)*std::sin(dy/2);return R*2*std::atan2(std::sqrt(h),std::sqrt((std::max)(0.0,1.0-h)));}

std::optional<Aircraft> match_aircraft(const BoardTarget& t,const std::vector<Aircraft>& list,std::string& why){
    if(t.object_id){
        DWORD oid=DWORD((std::max)(1.0,*t.object_id));
        for(auto& a:list){if(a.object_id==oid){why="direct SimObject ID "+std::to_string(oid);return a;}}
    }
    auto wanted=norm(t.callsign);
    if(wanted.empty()){why="empty callsign";return std::nullopt;}
    struct C{const Aircraft*a;int rank;double dist,alt,score;std::string why;};
    std::vector<C> id,pos;
    for(auto& a:list){
        C c{&a,99,INFINITY,INFINITY,INFINITY,{}};
        if(t.lat&&t.lon)c.dist=dist_m(*t.lat,*t.lon,a.lat,a.lon);
        if(t.alt)c.alt=std::abs(*t.alt-a.alt);
        auto atc=norm(a.atc_id), af=norm(a.airline+a.flight), fl=norm(a.flight);
        if(!atc.empty()&&atc==wanted){c.rank=0;c.why="exact ATC ID";}
        else if(!af.empty()&&af==wanted){c.rank=1;c.why="airline plus flight number";}
        else if(!fl.empty()&&wanted.size()>=fl.size()&&wanted.compare(wanted.size()-fl.size(),fl.size(),fl)==0){c.rank=2;c.why="flight-number suffix";}
        if(!c.why.empty())id.push_back(c);
        if(t.lat&&t.lon&&std::isfinite(c.dist)){
            double ta=t.alt.value_or(a.alt);
            double maxd=(ta<7000?6.0:12.0)*1852.0,maxa=ta<7000?2000.0:3500.0;
            if(c.dist<=maxd&&(!t.alt||c.alt<=maxa)){c.rank=10;c.why="guarded position/altitude fallback";c.score=c.dist/maxd+(t.alt?c.alt/maxa:0);pos.push_back(c);}
        }
    }
    auto describe=[](const C& c){std::ostringstream s;s<<c.why<<" SimObject "<<c.a->object_id;if(std::isfinite(c.dist))s<<" "<<std::fixed<<std::setprecision(2)<<c.dist/1852.0<<" NM";return s.str();};
    if(!id.empty()){std::sort(id.begin(),id.end(),[](auto&a,auto&b){if(a.rank!=b.rank)return a.rank<b.rank;if(a.dist!=b.dist)return a.dist<b.dist;return a.alt<b.alt;});why=describe(id.front());return *id.front().a;}
    if(pos.empty()){why="no match";return std::nullopt;}
    std::sort(pos.begin(),pos.end(),[](auto&a,auto&b){return a.score<b.score;});
    why=describe(pos.front());
    return *pos.front().a;
}

std::optional<std::string> http_get(const std::string& url,std::string& error){
    URL_COMPONENTS c{};c.dwStructSize=sizeof(c);c.dwSchemeLength=c.dwHostNameLength=c.dwUrlPathLength=c.dwExtraInfoLength=DWORD(-1);
    auto wu=widen(url);
    if(!WinHttpCrackUrl(wu.c_str(),0,0,&c)){error="CrackUrl failed";return{};}
    std::wstring host(c.lpszHostName,c.dwHostNameLength),path(c.lpszUrlPath,c.dwUrlPathLength);
    if(c.dwExtraInfoLength)path.append(c.lpszExtraInfo,c.dwExtraInfoLength);
    HINTERNET s=WinHttpOpen(L"OPSROOM-CameraBridge2024/0.23.2",WINHTTP_ACCESS_TYPE_NO_PROXY,WINHTTP_NO_PROXY_NAME,WINHTTP_NO_PROXY_BYPASS,0);
    if(!s){error="WinHttpOpen failed";return{};}
    WinHttpSetTimeouts(s,700,700,700,1100);
    HINTERNET cn=WinHttpConnect(s,host.c_str(),c.nPort,0);
    HINTERNET rq=cn?WinHttpOpenRequest(cn,L"GET",path.c_str(),nullptr,WINHTTP_NO_REFERER,WINHTTP_DEFAULT_ACCEPT_TYPES,c.nScheme==INTERNET_SCHEME_HTTPS?WINHTTP_FLAG_SECURE:0):nullptr;
    bool good=rq&&WinHttpSendRequest(rq,L"Accept: application/json\r\nCache-Control: no-cache\r\n",DWORD(-1),nullptr,0,0,0)&&WinHttpReceiveResponse(rq,nullptr);
    std::string body;
    while(good){
        DWORD a=0;if(!WinHttpQueryDataAvailable(rq,&a)){good=false;break;}
        if(!a)break;
        auto old=body.size();body.resize(old+a);DWORD rd=0;
        if(!WinHttpReadData(rq,body.data()+old,a,&rd)){good=false;break;}
        body.resize(old+rd);
    }
    if(rq)WinHttpCloseHandle(rq);if(cn)WinHttpCloseHandle(cn);WinHttpCloseHandle(s);
    if(!good){error="HTTP request failed";return{};}
    return body;
}

// Tiny JSON helpers. They intentionally read values only, never key names.
// This fixes the hotfix4 bug where `"callsign": null, "updated_at": ...` became target `updated_at`.
std::optional<size_t> find_value_start(const std::string& json,const std::string& key){
    std::string pat="\""+key+"\"";
    auto p=json.find(pat);
    if(p==std::string::npos)return{};
    p=json.find(':',p+pat.size());
    if(p==std::string::npos)return{};
    ++p;
    while(p<json.size()&&std::isspace((unsigned char)json[p]))++p;
    if(p>=json.size())return{};
    return p;
}

std::string read_json_string_at(const std::string& json,size_t p){
    if(p>=json.size()||json[p]!='"')return{};
    std::string out;
    for(++p;p<json.size();++p){
        char c=json[p];
        if(c=='"')break;
        if(c=='\\'&&p+1<json.size()){
            char e=json[++p];
            switch(e){case'n':out+='\n';break;case'r':out+='\r';break;case't':out+='\t';break;default:out+=e;break;}
        }else out+=c;
    }
    return out;
}

std::string find_string(const std::string& json,const std::string& key){
    auto p=find_value_start(json,key);
    if(!p||*p>=json.size()||json[*p]!='"')return{};
    return read_json_string_at(json,*p);
}

std::optional<double> find_num(const std::string& json,const std::string& key){
    auto p=find_value_start(json,key);
    if(!p)return{};
    if(json.compare(*p,4,"null")==0)return{};
    char* end=nullptr;
    double v=strtod(json.c_str()+*p,&end);
    if(end==json.c_str()+*p)return{};
    return v;
}

bool find_bool(const std::string& json,const std::string& key,bool fallback=false){
    auto p=find_value_start(json,key);
    if(!p)return fallback;
    if(json.compare(*p,4,"true")==0)return true;
    if(json.compare(*p,5,"false")==0)return false;
    return fallback;
}

std::string first_nonempty(std::initializer_list<std::string> values){
    for(auto& v:values){auto x=trim(v);if(!x.empty())return x;}
    return {};
}

std::optional<double> first_num(const std::string& body,std::initializer_list<const char*> keys){
    for(auto k:keys){auto v=find_num(body,k);if(v)return v;}
    return {};
}

CameraView parse_view(const std::string& body){
    CameraView v;
    v.mode=first_nonempty({find_string(body,"mode"),"tail_follow"});
    v.mode=upper(v.mode);
    std::replace(v.mode.begin(),v.mode.end(),'-','_');
    std::transform(v.mode.begin(),v.mode.end(),v.mode.begin(),[](unsigned char c){return char(std::tolower(c));});
    if(v.mode=="front_follow")v.mode="front_34";
    if(v.mode=="tower_drone")v.mode="tower_static";
    if(v.mode=="runway_end_drone")v.mode="runway_end_static";
    if(v.mode=="apron_drone")v.mode="apron_static";
    if(v.mode!="external_free"&&v.mode!="tail_follow"&&v.mode!="left_spotter"&&v.mode!="right_spotter"&&v.mode!="front_34"&&v.mode!="tower_static"&&v.mode!="runway_end_static"&&v.mode!="apron_static"&&v.mode!="orbit")v.mode="tail_follow";
    v.distance=(std::max)(5.0,(std::min)(1200.0,first_num(body,{"distance","distance_m"}).value_or(45.0)));
    v.height=(std::max)(-50.0,(std::min)(500.0,first_num(body,{"height","height_m"}).value_or(9.0)));
    v.side=(std::max)(-600.0,(std::min)(600.0,first_num(body,{"sideOffset","side_offset","side_offset_m"}).value_or(0.0)));
    v.pitch=(std::max)(-89.0,(std::min)(45.0,first_num(body,{"pitch","pitch_deg"}).value_or(-7.0)));
    v.orbit=std::fmod(first_num(body,{"orbitAngle","orbit_angle","orbit_angle_deg"}).value_or(180.0)+360.0,360.0);
    v.smoothing=(std::max)(0.0,(std::min)(0.98,first_num(body,{"smoothing"}).value_or(0.35)));
    return v;
}

std::optional<BoardTarget> parse_target(const std::string& body){
    BoardTarget t;
    t.command=upper(first_nonempty({find_string(body,"command"),find_string(body,"action")}));
    std::transform(t.command.begin(),t.command.end(),t.command.begin(),[](unsigned char c){return char(std::tolower(c));});
    t.released=find_bool(body,"released",false)||t.command=="release";
    t.view=parse_view(body);
    if(t.released)return t;

    t.callsign=norm(first_nonempty({
        find_string(body,"callsign"),
        find_string(body,"target_callsign"),
        find_string(body,"targetCallsign"),
        find_string(body,"label"),
        find_string(body,"target"),
        find_string(body,"flight")
    }));
    t.airport=upper(first_nonempty({find_string(body,"airport")}));
    t.tab=first_nonempty({find_string(body,"tab")});
    t.lat=first_num(body,{"latitude","lat"});
    t.lon=first_num(body,{"longitude","lon","lng"});
    t.alt=first_num(body,{"altitude","alt"});
    t.object_id=first_num(body,{"simObjectId","sim_object_id","objectId","object_id"});
    if(!t.valid())return{};
    return t;
}

std::string signature(const BoardTarget& t){
    std::ostringstream s;
    s<<t.command<<"|"<<(t.released?1:0)<<"|"<<t.callsign<<"|";
    if(t.object_id)s<<DWORD(*t.object_id);
    s<<"|"<<t.view.mode<<"|"<<t.view.distance<<"|"<<t.view.height<<"|"<<t.view.side<<"|"<<t.view.pitch<<"|"<<t.view.orbit<<"|"<<t.view.smoothing;
    return s.str();
}

enum:DWORD{DEF_AIRCRAFT=100,DEF_LIVE=101,DEF_USER=102,REQ_SCAN=200,REQ_LIVE=201,REQ_USER=202,EV_OBJECT_REMOVED=300};
std::vector<Aircraft> g_scan;
std::optional<Aircraft> g_user,g_match;
BoardTarget g_target;
std::string g_target_sig;
bool g_scan_pending=false,g_acquired=false;
int g_scan_attempts=0;
std::chrono::steady_clock::time_point g_scan_start{},g_last_msg{},g_next_scan{},g_next_reacquire{};
constexpr const char* CAMERA_CLIENT_NAME = "OPS ROOM CAMERA BRIDGE 2024";

SIMCONNECT_DATA_DEFINITION_ID def(DWORD v){return (SIMCONNECT_DATA_DEFINITION_ID)v;}
SIMCONNECT_DATA_REQUEST_ID req(DWORD v){return (SIMCONNECT_DATA_REQUEST_ID)v;}
SIMCONNECT_CLIENT_EVENT_ID ev(DWORD v){return (SIMCONNECT_CLIENT_EVENT_ID)v;}
void add_def(DWORD d,const char*n,const char*u,SIMCONNECT_DATATYPE t){auto r=SimConnect_AddToDataDefinition(g_sim,def(d),n,u,t);if(!ok(r))log(std::string("AddToDataDefinition failed ")+n+" "+hr(r));}
void define_aircraft(DWORD d){add_def(d,"ATC ID",nullptr,SIMCONNECT_DATATYPE_STRING32);add_def(d,"ATC AIRLINE",nullptr,SIMCONNECT_DATATYPE_STRING32);add_def(d,"ATC FLIGHT NUMBER",nullptr,SIMCONNECT_DATATYPE_STRING32);add_def(d,"TITLE",nullptr,SIMCONNECT_DATATYPE_STRING128);add_def(d,"PLANE LATITUDE","degrees",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"PLANE LONGITUDE","degrees",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"PLANE ALTITUDE","feet",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"PLANE HEADING DEGREES TRUE","degrees",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"PLANE PITCH DEGREES","degrees",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"PLANE BANK DEGREES","degrees",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"VELOCITY WORLD X","feet per second",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"VELOCITY WORLD Y","feet per second",SIMCONNECT_DATATYPE_FLOAT64);add_def(d,"VELOCITY WORLD Z","feet per second",SIMCONNECT_DATATYPE_FLOAT64);}
Aircraft unpack(DWORD id,const AircraftWire&w){return Aircraft{id,safe(w.atc_id,32),safe(w.airline,32),safe(w.flight,32),safe(w.title,128),w.lat,w.lon,w.alt,w.hdg,w.pitch,w.bank,w.vx,w.vy,w.vz};}


void send_cockpit_view_event(const std::string& why){
    if(!g_sim)return;
    struct EvtName{DWORD id; const char* name;};
    EvtName candidates[]={{9001,"VIEW_VIRTUAL_COCKPIT_FORWARD"},{9002,"VIEW_VIRTUAL_COCKPIT"},{9003,"VIEW_COCKPIT_FORWARD"},{9004,"VIEW_RESET"}};
    for(auto& e:candidates){
        auto mr=SimConnect_MapClientEventToSimEvent(g_sim, ev(e.id), e.name);
        if(ok(mr)){
            auto tr=SimConnect_TransmitClientEvent(g_sim, SIMCONNECT_OBJECT_ID_USER, ev(e.id), 0, SIMCONNECT_GROUP_PRIORITY_HIGHEST, SIMCONNECT_EVENT_FLAG_GROUPID_IS_PRIORITY);
            log(std::string("Cockpit view event ")+e.name+" "+hr(tr)+" "+why);
            if(ok(tr))break;
        }
    }
}

bool is_one_shot_camera_mode(const std::string& mode){
    // Static camera modes now acquire and HOLD until the explicit OPS ROOM
    // Release command. Do not self-release after placing the camera.
    return false;
}

std::string one_shot_sig(const Aircraft& a,const CameraView& v){
    std::ostringstream ss;ss<<a.object_id<<"|"<<v.mode<<"|"<<v.distance<<"|"<<v.height<<"|"<<v.side<<"|"<<v.pitch<<"|"<<v.orbit;return ss.str();
}

void return_camera_to_user_aircraft(const std::string& why){
    if(!g_sim)return;
    DWORD user_id = g_user ? g_user->object_id : SIMCONNECT_OBJECT_ID_USER;
    if(!g_acquired){
        auto ar=SimConnect_CameraAcquire(g_sim, CAMERA_CLIENT_NAME);
        log(std::string("CameraAcquire for user-aircraft return ")+hr(ar)+" "+why);
        g_acquired=ok(ar);
    }
    if(!g_acquired){
        log("User-aircraft camera return skipped because camera owner is unavailable: "+why);
        return;
    }
    SIMCONNECT_DATA_CAMERA cam{};
    cam.PositionReferential=SIMCONNECT_POSITION_REFERENTIAL_SIMOBJECT;
    cam.PositionReferentialObjectId=user_id;
    cam.Position.x=0.0;
    cam.Position.y=4.0;
    cam.Position.z=-18.0;
    cam.RotationReferential=SIMCONNECT_POSITION_REFERENTIAL_SIMOBJECT;
    cam.RotationReferentialObjectId=user_id;
    cam.Pbh.Pitch=-6.0;
    cam.Pbh.Bank=0.0;
    cam.Pbh.Heading=0.0;
    cam.Fov=0.85;
    DWORD mask=0xFFFFFFFF;
    auto sr=SimConnect_CameraSet(g_sim,cam,mask);
    log(std::string("CameraSet user-aircraft return ")+hr(sr)+" SimObject "+std::to_string(user_id)+" "+why);
    // Give MSFS one short frame window to accept the user-aircraft pose before owner release.
    std::this_thread::sleep_for(std::chrono::milliseconds(120));
}

void release_camera_control(const std::string& why){
    g_release_latched=true;
    return_camera_to_user_aircraft(why);
    send_cockpit_view_event(why);
    if(g_acquired&&g_sim){auto r=SimConnect_CameraRelease(g_sim, CAMERA_CLIENT_NAME);log(std::string("CameraRelease ")+hr(r)+" "+why);}
    g_acquired=false;
    g_match.reset();
    g_scan.clear();
    g_scan_pending=false;
    g_scan_attempts=0;
    g_one_shot_camera_sig.clear();
    g_next_reacquire=std::chrono::steady_clock::time_point::max();
    status("RELEASED","Camera released and cockpit-view fallback was requested. Select another aircraft from OPS ROOM/FIDS to reacquire.","","user aircraft / cockpit",true,&g_target.view);
}

void camera_set_for(const Aircraft& a){
    CameraView v=g_target.view;
    if(g_release_latched||g_target.released)return;
    if(is_one_shot_camera_mode(v.mode) && g_one_shot_camera_sig==one_shot_sig(a,v))return;
    if(!g_acquired){
        auto r=SimConnect_CameraAcquire(g_sim, CAMERA_CLIENT_NAME);
        log(std::string("CameraAcquire ")+hr(r));
        g_acquired=ok(r);
        if(!g_acquired){g_next_reacquire=std::chrono::steady_clock::now()+std::chrono::milliseconds(650);status("RECOVERING","Camera owner unavailable. Waiting to reacquire from MSFS Addons camera panel.",g_target.callsign,"SimObject "+std::to_string(a.object_id),true,&g_target.view);return;}
    }

    double x=v.side,y=v.height,z=-v.distance;
    if(v.mode=="left_spotter"){x=-(std::max)(std::abs(v.side),v.distance*0.55);z=-v.distance*0.25;}
    else if(v.mode=="right_spotter"){x=(std::max)(std::abs(v.side),v.distance*0.55);z=-v.distance*0.25;}
    else if(v.mode=="front_34"){x=(std::abs(v.side)>0.1?v.side:v.distance*0.42);z=v.distance*0.75;}
    else if(v.mode=="tower_static"){x=(std::abs(v.side)>0.1?v.side:v.distance*0.75);y=(std::max)(v.height,35.0);z=-v.distance*0.15;}
    else if(v.mode=="external_free"){x=(std::abs(v.side)>0.1?v.side:0.0);y=(std::max)(v.height,8.0);z=-std::max(v.distance,35.0);}
    else if(v.mode=="runway_end_static"){x=(std::abs(v.side)>0.1?v.side:0.0);y=(std::max)(v.height,28.0);z=std::max(v.distance,180.0);}
    else if(v.mode=="apron_static"){x=(std::abs(v.side)>0.1?v.side:v.distance*0.45);y=(std::max)(v.height,18.0);z=-std::max(v.distance,55.0);}
    else if(v.mode=="orbit"){constexpr double k=0.01745329251994329577;double a=v.orbit*k;x=std::sin(a)*v.distance+v.side;z=std::cos(a)*v.distance;}

    SIMCONNECT_DATA_CAMERA cam{};
    cam.PositionReferential=SIMCONNECT_POSITION_REFERENTIAL_SIMOBJECT;
    cam.PositionReferentialObjectId=a.object_id;
    cam.Position.x=x;
    cam.Position.y=y;
    cam.Position.z=z;
    cam.RotationReferential=SIMCONNECT_POSITION_REFERENTIAL_SIMOBJECT;
    cam.RotationReferentialObjectId=a.object_id;
    cam.Pbh.Pitch=v.pitch;
    cam.Pbh.Bank=0.0;
    cam.Pbh.Heading=0.0;
    cam.Fov=0.85;
    DWORD mask=0xFFFFFFFF;
    auto r=SimConnect_CameraSet(g_sim,cam,mask);
    if(!ok(r)){
        log(std::string("CameraSet failed ")+hr(r)+"; will reacquire without bridge restart");
        g_acquired=false;
        g_next_reacquire=std::chrono::steady_clock::now()+std::chrono::milliseconds(650);
        status("RECOVERING","CameraSet failed. Reacquiring camera owner without restarting bridge.",g_target.callsign,"SimObject "+std::to_string(a.object_id),true,&g_target.view);
        return;
    }
    if(v.mode=="tower_static"||v.mode=="runway_end_static"||v.mode=="apron_static"){
        status("STATIC VIEW","Stationary add-on camera is held until OPS ROOM Release.",g_target.callsign,"SimObject "+std::to_string(a.object_id),true,&g_target.view);
    }
}

void subscribe_live(DWORD object_id,const std::string& why){
    auto r=SimConnect_RequestDataOnSimObject(g_sim,req(REQ_LIVE),def(DEF_LIVE),object_id,SIMCONNECT_PERIOD_VISUAL_FRAME,SIMCONNECT_DATA_REQUEST_FLAG_DEFAULT);
    log(std::string("Live subscribe ")+hr(r)+" "+why);
}

void request_scan(){
    if(!g_target.valid()||g_target.released||g_scan_pending)return;
    if(g_target.object_id){
        DWORD oid=DWORD((std::max)(1.0,*g_target.object_id));
        g_match=Aircraft{};
        g_match->object_id=oid;
        subscribe_live(oid,"direct target");
        status("MATCHED","Using direct SimObject ID from OPS ROOM.",g_target.callsign,"SimObject "+std::to_string(oid),true,&g_target.view);
        return;
    }
    if(g_target.callsign.empty())return;
    if(g_scan_attempts>=20){status("MATCHING","Target not found after retry limit.",g_target.callsign,"none",true,&g_target.view);g_next_scan=std::chrono::steady_clock::now()+std::chrono::seconds(10);return;}
    if(!g_user){SimConnect_RequestDataOnSimObject(g_sim,req(REQ_USER),def(DEF_USER),SIMCONNECT_OBJECT_ID_USER,SIMCONNECT_PERIOD_ONCE,SIMCONNECT_DATA_REQUEST_FLAG_DEFAULT);g_next_scan=std::chrono::steady_clock::now()+std::chrono::milliseconds(500);return;}
    ++g_scan_attempts;
    g_scan.clear();
    g_scan_pending=true;
    g_scan_start=std::chrono::steady_clock::now();
    g_last_msg={};
    DWORD radius_m=300000;
    auto r=SimConnect_RequestDataOnSimObjectType(g_sim,req(REQ_SCAN),def(DEF_AIRCRAFT),radius_m,SIMCONNECT_SIMOBJECT_TYPE_AIRCRAFT);
    log(std::string("AI scan requested radius=")+std::to_string(radius_m)+" "+hr(r)+" target="+g_target.callsign);
}

void finish_scan(){
    g_scan_pending=false;
    if(g_user){g_scan.erase(std::remove_if(g_scan.begin(),g_scan.end(),[](const Aircraft&a){return a.object_id==g_user->object_id;}),g_scan.end());}
    std::string why;
    auto m=match_aircraft(g_target,g_scan,why);
    if(!m){log("Target not found: "+why);status("MATCHING","Target not found: "+why,g_target.callsign,"none",true,&g_target.view);g_next_scan=std::chrono::steady_clock::now()+std::chrono::seconds(3);return;}
    g_match=*m;
    g_scan_attempts=0;
    log("Matched "+g_target.callsign+" to "+why);
    status("MATCHED","Matched selected FIDS target",g_target.callsign,why,true,&g_target.view);
    subscribe_live(g_match->object_id,why);
}

void CALLBACK dispatch(SIMCONNECT_RECV* raw,DWORD,void*){
    switch(raw->dwID){
    case SIMCONNECT_RECV_ID_QUIT:g_quit=true;break;
    case SIMCONNECT_RECV_ID_SIMOBJECT_DATA:{
        auto*m=(SIMCONNECT_RECV_SIMOBJECT_DATA*)raw;
        if(m->dwDefineCount==0)break;
        auto*w=(AircraftWire*)&m->dwData;
        if(m->dwRequestID==REQ_USER){g_user=unpack(m->dwObjectID,*w);log("User SimObject "+std::to_string(g_user->object_id));}
        else if(m->dwRequestID==REQ_LIVE){auto live=unpack(m->dwObjectID,*w);g_match=live;camera_set_for(live);if(!is_one_shot_camera_mode(g_target.view.mode)){bool st=g_target.view.mode=="tower_static"||g_target.view.mode=="runway_end_static"||g_target.view.mode=="apron_static";status(st?"STATIC VIEW":"FOLLOWING",st?"Stationary add-on camera is held until OPS ROOM Release.":"Camera follows selected MSFS 2024 SimObject",g_target.callsign,"SimObject "+std::to_string(live.object_id),true,&g_target.view);}}
        break;
    }
    case SIMCONNECT_RECV_ID_SIMOBJECT_DATA_BYTYPE:{
        auto*m=(SIMCONNECT_RECV_SIMOBJECT_DATA_BYTYPE*)raw;
        if(m->dwRequestID!=REQ_SCAN||m->dwDefineCount==0)break;
        auto*w=(AircraftWire*)&m->dwData;
        g_scan.push_back(unpack(m->dwObjectID,*w));
        g_last_msg=std::chrono::steady_clock::now();
        break;
    }
    case SIMCONNECT_RECV_ID_CAMERA_DATA:{
        auto*m=(SIMCONNECT_RECV_CAMERA_DATA*)raw;
        g_camera_get_x.store(m->CameraData.Position.x);
        g_camera_get_y.store(m->CameraData.Position.y);
        g_camera_get_z.store(m->CameraData.Position.z);
        g_camera_get_at=std::chrono::steady_clock::now();
        break;
    }
    case SIMCONNECT_RECV_ID_EXCEPTION:{
        auto*e=(SIMCONNECT_RECV_EXCEPTION*)raw;
        log("SimConnect exception "+std::to_string(e->dwException));
        break;
    }
    default:break;
    }
}

BOOL WINAPI ctrl(DWORD){g_quit=true;return TRUE;}
}

int main(){
    SetConsoleCtrlHandler(ctrl,TRUE);
    std::string base=local_appdata()+"\\Ops Room";
    g_log_path=env_or("OPSROOM_CAMERA_LOG_PATH",base+"\\logs\\camera_bridge_2024.log");
    g_status_path=env_or("OPSROOM_CAMERA_STATUS_PATH",base+"\\camera_bridge_2024_status.json");
    g_target_url=env_or("OPSROOM_CAMERA_TARGET_URL","http://127.0.0.1:8080/api/camera/target");

    log("OPS ROOM Camera Bridge 2024 starting.");
    status("STARTING","Bridge process starting");
    std::printf("OPS ROOM Camera Bridge 2024 starting. Waiting for MSFS 2024 SimConnect...\n");
    std::fflush(stdout);

    HRESULT r=E_FAIL;
    while(!g_quit&&!g_sim){
        r=SimConnect_Open(&g_sim,"OPS ROOM Camera Bridge 2024",nullptr,0,0,0);
        if(ok(r)&&g_sim)break;
        g_sim=nullptr;
        std::string msg="MSFS 2024 SimConnect is not available yet. Start MSFS 2024 and load into a flight. Retrying in 5 seconds. Last error "+hr(r);
        log("SimConnect_Open failed "+hr(r)+"; retrying in 5 seconds.");
        status("WAITING SIMCONNECT",msg,"","",true);
        std::printf("[%s] %s\n",now_iso().c_str(),msg.c_str());
        std::fflush(stdout);
        for(int i=0;i<50&&!g_quit;++i)std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    if(g_quit){status("STOPPED","Bridge stopped before SimConnect connected.","","",false);log("OPS ROOM Camera Bridge 2024 stopped before SimConnect connected.");return 0;}

    log("SimConnect connected.");
    std::printf("[%s] SimConnect connected. Waiting for OPS ROOM FIDS target.\n",now_iso().c_str());
    std::fflush(stdout);

    define_aircraft(DEF_AIRCRAFT);
    define_aircraft(DEF_LIVE);
    define_aircraft(DEF_USER);
    SimConnect_RequestDataOnSimObject(g_sim,req(REQ_USER),def(DEF_USER),SIMCONNECT_OBJECT_ID_USER,SIMCONNECT_PERIOD_ONCE,SIMCONNECT_DATA_REQUEST_FLAG_DEFAULT);
    status("CONNECTED","Connected to SimConnect. Waiting for OPS ROOM FIDS target.");

    auto next_poll=std::chrono::steady_clock::now();
    while(!g_quit){
        HRESULT dispatch_hr = SimConnect_CallDispatch(g_sim,dispatch,nullptr);
        if(FAILED(dispatch_hr)){
            log("SimConnect dispatch failed " + hr(dispatch_hr) + "; stopping bridge.");
            status("STOPPED","SimConnect connection closed. Bridge stopped.","","",false);
            g_quit = true;
            break;
        }
        auto now=std::chrono::steady_clock::now();

        if(now>=next_poll){
            std::string er;
            auto body=http_get(g_target_url,er);
            if(body){
                auto t=parse_target(*body);
                if(t){
                    auto sig=signature(*t);
                    if(sig!=g_target_sig){
                        if(t->released){
                            g_target=*t;
                            g_target_sig=sig;
                            log("Release command from OPS ROOM.");
                            release_camera_control("OPS ROOM release command");
                        }else{
                            if(g_release_latched && t->command=="view"){
                                continue;
                            }
                            g_release_latched=false;
                            if(t->view.mode!=g_target.view.mode)g_one_shot_camera_sig.clear();
                            bool identity_changed=norm(t->callsign)!=norm(g_target.callsign)||t->object_id!=g_target.object_id;
                            g_target=*t;
                            g_target_sig=sig;
                            if(identity_changed){
                                g_match.reset();
                                g_scan_attempts=0;
                                log("New target from OPS ROOM: "+(g_target.callsign.empty()?std::string("SimObject ")+std::to_string(DWORD(g_target.object_id.value_or(0))):g_target.callsign)+" mode="+g_target.view.mode);
                                status("TARGET RECEIVED","Target received from OPS ROOM. Matching SimObject...",g_target.callsign,"none",true,&g_target.view);
                                g_next_scan=now;
                            }else{
                                log("Camera view updated: "+g_target.view.mode);
                                status(g_match?"FOLLOWING":"TARGET RECEIVED","Camera view updated from OPS ROOM.",g_target.callsign,g_match?("SimObject "+std::to_string(g_match->object_id)):"none",true,&g_target.view);
                            }
                        }
                    }
                }
            }else{
                status("WAITING OPS ROOM","Could not poll OPS ROOM target endpoint: "+er,"","",true);
            }
            next_poll=now+std::chrono::milliseconds(700);
        }

        if(g_match&&!g_acquired&&!g_target.released&&!g_release_latched&&now>=g_next_reacquire){
            log("Camera owner reacquire retry without bridge restart.");
            camera_set_for(*g_match);
            g_next_reacquire=now+std::chrono::milliseconds(850);
        }

        if(g_scan_pending){
            bool quiet=g_last_msg.time_since_epoch().count()!=0&&now-g_last_msg>std::chrono::milliseconds(450);
            bool timeout=now-g_scan_start>std::chrono::seconds(5);
            if(quiet||timeout)finish_scan();
        }
        if(g_target.valid()&&!g_target.released&&!g_match&&!g_scan_pending&&now>=g_next_scan)request_scan();

        if(now-g_camera_get_at>=std::chrono::milliseconds(1500)&&g_sim){
            SimConnect_CameraGet(g_sim,SIMCONNECT_POSITION_REFERENTIAL_SIMOBJECT);
        }
        if(now-g_camera_status_at>=std::chrono::milliseconds(1500)){
            g_camera_status_at=now;
            status(g_acquired&&g_match?"FOLLOWING":(g_acquired?"ACQUIRED":"CONNECTED"),"Camera position status update.",g_target.callsign,g_match?("SimObject "+std::to_string(g_match->object_id)):"none",true,g_match?&g_target.view:nullptr);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }

    if(g_sim){
        if(g_acquired)SimConnect_CameraRelease(g_sim, CAMERA_CLIENT_NAME);
        SimConnect_Close(g_sim);
    }
    status("STOPPED","Bridge stopped","","",false);
    log("OPS ROOM Camera Bridge 2024 stopped.");
    return 0;
}
