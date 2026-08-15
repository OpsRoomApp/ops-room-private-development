/*
 * OPS ROOM in-sim panel: OpenLayers stub.
 *
 * The Live Map uses OpenLayers 10, which cannot run in the Coherent GT
 * (Chrome 49) in-sim webview. The panel therefore omits the real OpenLayers
 * library; this stub supplies the `ol.*` surface the map module touches so
 * opening the map shows a clear "not available here" placeholder instead of
 * throwing. Every other module is unaffected. ES5 only.
 */
(function (global) {
  'use strict';

  function noop() { return undefined; }

  function emptyObject() { return {}; }

  function viewStub() {
    return {
      getCenter: function () { return [0, 0]; },
      setCenter: noop,
      getZoom: function () { return 8; },
      setZoom: noop,
      getRotation: function () { return 0; },
      setRotation: noop,
      animate: noop,
      fit: noop,
      calculateExtent: function () { return [0, 0, 0, 0]; },
      on: noop,
      un: noop
    };
  }

  function mapStub(targetElement) {
    return {
      getView: viewStub,
      getTargetElement: function () { return targetElement; },
      getSize: function () { return [800, 600]; },
      updateSize: noop,
      on: noop,
      un: noop,
      forEachFeatureAtPixel: function () { return undefined; }
    };
  }

  function featureStub() {
    return {
      get: function () { return null; },
      set: noop,
      setGeometry: noop,
      getGeometry: function () { return null; },
      setStyle: noop,
      getId: function () { return 0; }
    };
  }

  // Any leaf in these namespaces is constructed with `new ol.X.Y(...)`; a
  // plain function that returns an empty object is safe for every one of them.
  function makeNamespace(names) {
    var ns = {};
    for (var i = 0; i < names.length; i++) {
      ns[names[i]] = emptyObject;
    }
    return ns;
  }

  var ol = {};

  ol.Map = function (opts) {
    var target = opts && opts.target;
    var el = target && (typeof target === 'string' ? document.getElementById(target) : target);
    if (el) {
      el.innerHTML =
        '<div style="display:flex;height:100%;align-items:center;justify-content:center;' +
        'color:#a7a6a1;font-family:B612,Arial,sans-serif;text-align:center;padding:24px;box-sizing:border-box;">' +
        'Live Map is not available in the in-game panel.</div>';
    }
    return mapStub(el);
  };

  ol.View = function () { return viewStub(); };
  ol.Feature = function () { return featureStub(); };

  ol.style = makeNamespace(['Circle', 'Fill', 'Icon', 'RegularShape', 'Stroke', 'Style', 'Text']);
  ol.geom = makeNamespace(['Circle', 'LineString', 'Point', 'Polygon']);
  ol.layer = makeNamespace(['Tile', 'Vector', 'VectorTile']);
  ol.source = makeNamespace(['OSM', 'Vector', 'VectorTile', 'XYZ']);
  ol.format = makeNamespace(['GeoJSON', 'MVT']);

  ol.proj = {
    fromLonLat: function (c) { return c || [0, 0]; },
    toLonLat: function (c) { return c || [0, 0]; },
    transformExtent: function (e) { return e || [0, 0, 0, 0]; }
  };

  ol.extent = {
    buffer: function (e) { return e || [0, 0, 0, 0]; },
    containsCoordinate: function () { return false; },
    getCenter: function () { return [0, 0]; },
    getWidth: function () { return 0; }
  };

  ol.control = {
    Attribution: emptyObject,
    defaults: {
      defaults: function () {
        return { extend: function () { return []; } };
      }
    }
  };

  global.ol = ol;
})(typeof window !== 'undefined' ? window : this);
