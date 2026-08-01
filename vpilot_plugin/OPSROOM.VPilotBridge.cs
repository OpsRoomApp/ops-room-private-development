using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using RossCarlson.Vatsim.Vpilot.Plugins;

namespace OpsRoom.VPilotBridge
{
    public sealed class Plugin : IPlugin
    {
        private IBroker _broker;
        private Timer _timer;
        private int _tickRunning;
        private bool _networkConnected;
        private bool _observerMode;
        private string _cid;
        private string _callsign;
        private string _typeCode;
        private string _selcal;
        private readonly HttpClient _http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        private readonly JavaScriptSerializer _json = new JavaScriptSerializer();

        public string Name { get { return "OPS ROOM Bridge"; } }

        public void Initialize(IBroker broker)
        {
            _broker = broker;
            Subscribe();
            _timer = new Timer(Tick, null, TimeSpan.Zero, TimeSpan.FromSeconds(1));
            SafeDebug("OPS ROOM Bridge initialized.");
        }

        private void Subscribe()
        {
            _broker.SessionEnded += (sender, args) =>
            {
                PostEvent(new Dictionary<string, object> { { "type", "session_ended" } });
                try { if (_timer != null) _timer.Dispose(); } catch { }
            };
            _broker.NetworkConnected += (sender, args) =>
            {
                _networkConnected = true;
                _cid = args.Cid;
                _callsign = args.Callsign;
                _typeCode = args.TypeCode;
                _selcal = args.SelcalCode;
                _observerMode = args.ObserverMode;
                PostEvent(new Dictionary<string, object> {
                    { "type", "network_connected" }, { "cid", _cid }, { "callsign", _callsign },
                    { "type_code", _typeCode }, { "selcal", _selcal }, { "observer_mode", _observerMode }
                });
            };
            _broker.NetworkDisconnected += (sender, args) =>
            {
                _networkConnected = false;
                PostEvent(new Dictionary<string, object> { { "type", "network_disconnected" }, { "callsign", _callsign } });
            };
            _broker.PrivateMessageReceived += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "private_message" }, { "from", args.From }, { "message", args.Message }, { "outbound", false }
            });
            _broker.RadioMessageReceived += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "radio_message" }, { "from", args.From }, { "message", args.Message }, { "frequencies", args.Frequencies }
            });
            _broker.BroadcastMessageReceived += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "broadcast_message" }, { "from", args.From }, { "message", args.Message }
            });
            _broker.MetarReceived += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "metar" }, { "message", args.Metar }
            });
            _broker.AtisReceived += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "atis" }, { "from", args.From }, { "lines", args.Lines }
            });
            _broker.ControllerAdded += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "controller_added" }, { "callsign", args.Callsign }, { "frequency", args.Frequency },
                { "latitude", args.Latitude }, { "longitude", args.Longitude }
            });
            _broker.ControllerDeleted += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "controller_deleted" }, { "callsign", args.Callsign }
            });
            _broker.ControllerFrequencyChanged += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "controller_frequency_changed" }, { "callsign", args.Callsign }, { "frequency", args.NewFrequency }
            });
            _broker.ControllerLocationChanged += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "controller_location_changed" }, { "callsign", args.Callsign },
                { "latitude", args.NewLatitude }, { "longitude", args.NewLongitude }
            });
            _broker.SelcalAlertReceived += (sender, args) => PostEvent(new Dictionary<string, object> {
                { "type", "selcal" }, { "from", args.From }, { "frequencies", args.Frequencies },
                { "message", "SELCAL ALERT" }
            });
        }

        private void Tick(object state)
        {
            if (Interlocked.Exchange(ref _tickRunning, 1) == 1) return;
            try
            {
                SendHeartbeat();
                PollCommands();
            }
            catch
            {
                // An unavailable OPS ROOM host must never affect vPilot.
            }
            finally
            {
                Interlocked.Exchange(ref _tickRunning, 0);
            }
        }

        private void SendHeartbeat()
        {
            var payload = new Dictionary<string, object>();
            payload["version"] = "0.18.7";
            payload["network_connected"] = _networkConnected;
            payload["observer_mode"] = _observerMode;
            payload["cid"] = _cid;
            payload["callsign"] = _callsign;
            payload["type_code"] = _typeCode;
            payload["selcal"] = _selcal;
            payload["capabilities"] = new[] {
                "PrivateMessageReceived", "SendPrivateMessage", "RadioMessageReceived", "SendRadioMessage",
                "RequestMetar", "RequestAtis", "ControllerAdded", "ControllerFrequencyChanged",
                "SelcalAlertReceived", "SetModeC", "SquawkIdent"
            };
            PostJson("/api/vpilot/bridge/heartbeat", payload);
        }

        private void PollCommands()
        {
            string response = _http.GetStringAsync(GetBaseUrl() + "/api/vpilot/bridge/commands").GetAwaiter().GetResult();
            var root = _json.DeserializeObject(response) as Dictionary<string, object>;
            if (root == null || !root.ContainsKey("commands")) return;
            var commands = root["commands"] as IEnumerable;
            if (commands == null) return;
            foreach (object raw in commands)
            {
                var command = raw as Dictionary<string, object>;
                if (command != null) ExecuteCommand(command);
            }
        }

        private void ExecuteCommand(Dictionary<string, object> command)
        {
            int id = command.ContainsKey("id") ? Convert.ToInt32(command["id"]) : 0;
            string action = command.ContainsKey("action") ? Convert.ToString(command["action"]) : "";
            var payload = command.ContainsKey("payload") ? command["payload"] as Dictionary<string, object> : null;
            bool success = false;
            string detail = "";
            try
            {
                if (action == "send_private_message")
                {
                    string to = payload != null && payload.ContainsKey("to") ? Convert.ToString(payload["to"]) : "";
                    string message = payload != null && payload.ContainsKey("message") ? Convert.ToString(payload["message"]) : "";
                    _broker.SendPrivateMessage(to, message);
                    success = true;
                    detail = "Private message sent";
                    PostEvent(new Dictionary<string, object> {
                        { "type", "private_message" }, { "to", to }, { "message", message }, { "outbound", true }
                    });
                }
                else if (action == "send_radio_message")
                {
                    string message = payload != null && payload.ContainsKey("message") ? Convert.ToString(payload["message"]) : "";
                    SendRadioMessageThroughBroker(message);
                    success = true;
                    detail = "Radio message transmitted";
                    PostEvent(new Dictionary<string, object> {
                        { "type", "radio_message" }, { "to", "FREQUENCY" }, { "message", message }, { "outbound", true }
                    });
                }
                else if (action == "set_mode_c")
                {
                    bool enabled = payload != null && payload.ContainsKey("enabled") && Convert.ToBoolean(payload["enabled"]);
                    _broker.SetModeC(enabled);
                    success = true;
                    detail = enabled ? "Mode C enabled" : "Mode C disabled";
                }
                else if (action == "squawk_ident")
                {
                    _broker.SquawkIdent();
                    success = true;
                    detail = "IDENT transmitted";
                }
                else
                {
                    detail = "Unsupported command";
                }
            }
            catch (Exception ex)
            {
                detail = ex.GetType().Name + ": " + ex.Message;
            }
            PostEvent(new Dictionary<string, object> {
                { "type", "command_result" }, { "command_id", id }, { "action", action },
                { "success", success }, { "message", detail }
            });
        }


        private void SendRadioMessageThroughBroker(string message)
        {
            if (String.IsNullOrWhiteSpace(message)) throw new InvalidOperationException("Message is required");
            var brokerType = _broker.GetType();
            var oneArg = brokerType.GetMethod("SendRadioMessage", new[] { typeof(string) });
            if (oneArg != null)
            {
                oneArg.Invoke(_broker, new object[] { message });
                return;
            }
            var methods = brokerType.GetMethods().Where(m => m.Name == "SendRadioMessage").ToArray();
            foreach (var method in methods)
            {
                var parameters = method.GetParameters();
                if (parameters.Length == 1)
                {
                    method.Invoke(_broker, new object[] { message });
                    return;
                }
                if (parameters.Length == 2)
                {
                    method.Invoke(_broker, new object[] { null, message });
                    return;
                }
            }
            throw new MissingMethodException("vPilot broker does not expose SendRadioMessage");
        }

        private void PostEvent(Dictionary<string, object> payload)
        {
            payload["received_utc"] = DateTime.UtcNow.ToString("o");
            ThreadPool.QueueUserWorkItem(delegate
            {
                try { PostJson("/api/vpilot/bridge/event", payload); } catch { }
            });
        }

        private void PostJson(string path, Dictionary<string, object> payload)
        {
            var content = new StringContent(_json.Serialize(payload), Encoding.UTF8, "application/json");
            _http.PostAsync(GetBaseUrl() + path, content).GetAwaiter().GetResult();
        }

        private void SafeDebug(string text)
        {
            try { _broker.PostDebugMessage(text); } catch { }
        }

        private string GetBaseUrl()
        {
            try
            {
                string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Ops Room", "settings.json");
                if (File.Exists(path))
                {
                    var root = _json.DeserializeObject(File.ReadAllText(path)) as Dictionary<string, object>;
                    var server = root != null && root.ContainsKey("server") ? root["server"] as Dictionary<string, object> : null;
                    if (server != null && server.ContainsKey("port"))
                    {
                        int port = Convert.ToInt32(server["port"]);
                        if (port >= 1024 && port <= 65535) return "http://127.0.0.1:" + port;
                    }
                }
            }
            catch { }
            return "http://127.0.0.1:8080";
        }
    }
}
