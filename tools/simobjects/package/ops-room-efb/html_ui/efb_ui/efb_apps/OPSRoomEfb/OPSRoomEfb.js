/*
 * OPS ROOM EFB app for the native MSFS 2024 EFB.
 *
 * Mirrors the proven third-party EFB apps that embed a localhost page (the
 * same architecture GSX and Fenix use). The EFB OS loads this script and
 * calls ``Efb.use(...)``; the app then renders a full-bleed <iframe> pointed
 * at the OPS ROOM desktop app's localhost legacy build.
 *
 * Two things matter here, and both are copied from the working reference apps:
 *
 * 1. The EFB OS (EFBViewService) drives each app's view through a fixed set of
 *    lifecycle methods it calls on the view instance: onOpen, onResume,
 *    onPause, onClose, onUpdate, routeGamepadInteractionEvent and
 *    handlePageKeyAction. A view that lacks any of these makes the OS throw
 *    inside its requestAnimationFrame update loop, which freezes the entire
 *    EFB. So OPSRoomView implements every one of them.
 *
 * 2. The iframe is only pointed at the app once the localhost server answers
 *    (a fetch to the CORS-open /api/panel/health probe), then retried on a
 *    timer while it is down. The app page posts an "opsroom-ready" message
 *    once its own script has run, which is what hides the waiting overlay.
 */
!function (sdk) {
  "use strict";

  // ------------------------------------------------------------------
  // EFB app SDK boilerplate (Container + App). This is the standard,
  // version-stable registration surface shared by every EFB app; it is
  // bundled into each app because the EFB OS shares the container via
  // ``window.EFB_API``. Mirrors the official fs-base-efb-app-* apps.
  // ------------------------------------------------------------------
  var AppBootMode = { COLD: 0, WARM: 1, HOT: 2 };
  var AppSuspendMode = { SLEEP: 0, TERMINATE: 1 };
  var _uid = 0;

  class Container {
    constructor() {
      this._uid = _uid++;
      this._registeredAppsPromises = [];
      this._installedApps = sdk.ArraySubject.create();
    }
    static get instance() {
      return (window.EFB_API = Container._instance =
        window.EFB_API || Container._instance || new Container());
    }
    apps() { return this._installedApps; }
    allAppsLoaded() { return this._registeredAppsPromises.length === this._installedApps.length; }
    setBus(bus) { this.bus = bus; return this; }
    setUnitsSettingManager(m) { this.unitsSettingManager = m; return this; }
    setEfbSettingManager(m) { this.efbSettingsManager = m; return this; }
    setOnboardingManager(m) { this.onboardingManager = m; return this; }
    setNotificationManager(m) { this.notificationManager = m; return this; }

    async loadCss(uri) {
      if (document.querySelector('link[href*="' + uri + '"]')) {
        return Promise.reject(uri + " already loaded.");
      }
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = uri;
      document.head.appendChild(link);
      return new Promise(function (resolve, reject) {
        link.onload = function () { resolve(); };
        link.onerror = reject;
      });
    }

    use(app) {
      try {
        if (!this.bus) throw new Error("Bus has not been initialized yet.");
        const instance = app instanceof App ? app : new app();
        const installProps = {
          bus: this.bus,
          unitsSettingManager: this.unitsSettingManager,
          efbSettingsManager: this.efbSettingsManager,
          notificationManager: this.notificationManager,
          onboardingManager: this.onboardingManager,
          options: {}
        };
        const installer = instance._install(installProps);
        const name = instance.internalName;
        if (/\s/.test(name)) {
          throw new Error('The App name can\'t have any whitespace character. "' + name + '"');
        }
        const container = this;
        this._registeredAppsPromises.push(
          installer.then(() => { container._installedApps.insert(instance); })
        );
      } catch (err) {
        try { if (document.currentScript) document.currentScript.remove(); } catch (e) {}
        console.error("App can't be installed", err);
        throw err;
      }
      return this;
    }
  }

  const Efb = Container.instance;
  const EfbApiVersion = "1.0.3";

  class App {
    constructor() {
      this._isInstalled = false;
      this._isReady = false;
      this._favoriteIndex = -1;
      this.available = sdk.Subject.create(true);
      this.BootMode = AppBootMode.COLD;
      this.SuspendMode = AppSuspendMode.SLEEP;
    }
    async _install(props) {
      if (this._isInstalled) return Promise.reject("App already installed.");
      this._isInstalled = true;
      this.bus = props.bus;
      this._unitsSettingManager = props.unitsSettingManager;
      this._efbSettingsManager = props.efbSettingsManager;
      this._notificationManager = props.notificationManager;
      this._onboardingManager = props.onboardingManager;
      this._favoriteIndex = props.favoriteIndex != null ? props.favoriteIndex : -1;
      this.options = props.options;
      await this.install(props);
      this._isReady = true;
      Coherent.trigger("EFB_APP_INSTALLED", this.name, this.internalName, EfbApiVersion, this.getVersion());
      return Promise.resolve();
    }
    async install() { return Promise.resolve(); }
    get isReady() { return this._isReady; }
    get internalName() { return this.constructor.name; }
    get unitsSettingsManager() { if (!this._unitsSettingManager) throw new Error("Units settings manager is not defined"); return this._unitsSettingManager; }
    get efbSettingsManager() { if (!this._efbSettingsManager) throw new Error("EFB settings manager is not defined"); return this._efbSettingsManager; }
    get notificationManager() { if (!this._notificationManager) throw new Error("Notification manager is not defined"); return this._notificationManager; }
    get onboardingManager() { if (!this._onboardingManager) throw new Error("Onboarding manager is not defined"); return this._onboardingManager; }
    get compatibleAircraftModels() { return undefined; }
    get favoriteIndex() { return this._favoriteIndex; }
    set favoriteIndex(v) { this._favoriteIndex = v; }
    getIsSearchable() { return !this.options || this.options.isSearchable == null ? true : this.options.isSearchable; }
    getIsFavoritable() { return !this.options || this.options.isFavoritable == null ? true : this.options.isFavoritable; }
    getVersion() { return ""; }
  }

  // ------------------------------------------------------------------
  // OPS ROOM app
  // ------------------------------------------------------------------
  const BASE_URL = "coui://html_ui/efb_ui/efb_apps/OPSRoomEfb";
  const APP_ORIGIN = "http://127.0.0.1:8080";
  const APP_PATH = "/static/index.legacy.html?efb=1";
  const HEALTH_PATH = "/api/panel/health";   // CORS-open liveness probe
  const RETRY_MS = 2000;

  class OPSRoomView extends sdk.DisplayComponent {
    constructor() {
      super(...arguments);
      this.rootRef = sdk.FSComponent.createRef();
      this.frameRef = sdk.FSComponent.createRef();
      this.waitRef = sdk.FSComponent.createRef();
      this.connected = false;
      this.checking = false;
      this.checkInterval = null;
      this.onMessage = this.onMessage.bind(this);
    }

    render() {
      return sdk.FSComponent.buildComponent(
        "div",
        { ref: this.rootRef, class: "opsroom-efb" },
        sdk.FSComponent.buildComponent("iframe", {
          ref: this.frameRef,
          class: "opsroom-frame",
          width: "100%",
          height: "100%",
          frameBorder: "0",
          allowFullScreen: true
        }),
        sdk.FSComponent.buildComponent(
          "div",
          { ref: this.waitRef, class: "opsroom-efb-waiting" },
          sdk.FSComponent.buildComponent("div", { class: "opsroom-efb-spinner" }),
          sdk.FSComponent.buildComponent("div", { class: "opsroom-efb-waiting-title" }, "OPS ROOM"),
          sdk.FSComponent.buildComponent("div", { class: "opsroom-efb-waiting-text" }, "Waiting for the OPS ROOM app\u2026")
        )
      );
    }

    onAfterRender() {
      super.onAfterRender();
      window.addEventListener("message", this.onMessage);
    }

    // --- EFB OS lifecycle. The OS calls these on the view instance; every one
    // must exist or the OS's update loop throws and freezes the whole EFB. ---
    onOpen() {
      this.startPolling();
    }
    onResume() {
      // Re-check if we never managed to connect (server was down on open).
      this.connect();
    }
    onPause() {
      // Keep the iframe mounted so switching back is instant.
    }
    onClose() {
      this.teardown();
    }
    onUpdate(time) {
      // No per-frame work.
    }
    routeGamepadInteractionEvent(ev) {
      // No gamepad UI.
    }
    handlePageKeyAction(key, args) {
      // No deep links.
    }

    startPolling() {
      if (this.checkInterval !== null) return;
      this.connect();
      this.checkInterval = window.setInterval(this.connect.bind(this), RETRY_MS);
    }

    connect() {
      if (this.connected || this.checking) return;
      this.checking = true;
      const self = this;
      fetch(APP_ORIGIN + HEALTH_PATH).then(
        function () { self.checking = false; self.onHealthOk(); },
        function () { self.checking = false; }
      );
    }

    onHealthOk() {
      if (this.connected) return;
      this.connected = true;
      const frame = this.frameRef.getOrDefault();
      if (frame) frame.setAttribute("src", APP_ORIGIN + APP_PATH + "&t=" + Date.now());
      this.stopPolling();
    }

    stopPolling() {
      if (this.checkInterval !== null) {
        window.clearInterval(this.checkInterval);
        this.checkInterval = null;
      }
    }

    // The hosted app posts {type:"opsroom-ready"} once its own script has run,
    // which is the only reliable "the real client is up" signal (the iframe
    // load event also fires for a browser error document).
    onMessage(ev) {
      const data = ev.data;
      if (!data || data.type !== "opsroom-ready") return;
      const wait = this.waitRef.getOrDefault();
      if (wait) wait.style.display = "none";
    }

    teardown() {
      this.stopPolling();
      window.removeEventListener("message", this.onMessage);
    }

    destroy() {
      this.teardown();
      super.destroy();
    }
  }

  Efb.use(
    class OPSRoomEfb extends App {
      get name() { return "OPS ROOM"; }
      get icon() { return BASE_URL + "/Assets/app-icon.svg"; }
      async install() {
        // CSS is cosmetic; never let a stylesheet failure block registration.
        try { await Efb.loadCss(BASE_URL + "/OPSRoomEfb.css"); } catch (e) {}
      }
      render() { return sdk.FSComponent.buildComponent(OPSRoomView, { bus: this.bus }); }
    }
  );
}(msfssdk);
