/*
 * OPS ROOM in-sim panel polyfills.
 *
 * The MSFS in-game webview is Coherent GT (Chromium 49), which predates a
 * handful of runtime APIs the OPS ROOM frontend uses. This file fills only
 * those gaps so the transpiled bundle can run unchanged. Everything here is
 * ES5 so this file itself parses in Chrome 49.
 */
(function (global) {
  'use strict';

  // globalThis (Chrome 71)
  if (typeof global.globalThis === 'undefined') {
    global.globalThis = global;
  }

  // Object.entries / Object.values (Chrome 54)
  if (typeof Object.entries !== 'function') {
    Object.entries = function (obj) {
      var keys = Object.keys(obj);
      var out = [];
      for (var i = 0; i < keys.length; i++) {
        out.push([keys[i], obj[keys[i]]]);
      }
      return out;
    };
  }
  if (typeof Object.values !== 'function') {
    Object.values = function (obj) {
      var keys = Object.keys(obj);
      var out = [];
      for (var i = 0; i < keys.length; i++) {
        out.push(obj[keys[i]]);
      }
      return out;
    };
  }

  // String.prototype.padStart / padEnd (Chrome 57)
  if (typeof String.prototype.padStart !== 'function') {
    String.prototype.padStart = function (targetLength, padString) {
      var str = String(this);
      targetLength = targetLength >> 0;
      if (str.length >= targetLength) { return str; }
      var pad = padString !== undefined ? String(padString) : ' ';
      var fill = '';
      while (fill.length < targetLength - str.length) { fill += pad; }
      if (fill.length > targetLength - str.length) { fill = fill.slice(0, targetLength - str.length); }
      return fill + str;
    };
  }
  if (typeof String.prototype.padEnd !== 'function') {
    String.prototype.padEnd = function (targetLength, padString) {
      var str = String(this);
      targetLength = targetLength >> 0;
      if (str.length >= targetLength) { return str; }
      var pad = padString !== undefined ? String(padString) : ' ';
      var fill = '';
      while (fill.length < targetLength - str.length) { fill += pad; }
      if (fill.length > targetLength - str.length) { fill = fill.slice(0, targetLength - str.length); }
      return str + fill;
    };
  }

  // Array.prototype.flatMap (Chrome 69)
  if (typeof Array.prototype.flatMap !== 'function') {
    Array.prototype.flatMap = function (callback, thisArg) {
      var out = [];
      for (var i = 0; i < this.length; i++) {
        var item = callback.call(thisArg, this[i], i, this);
        if (Array.isArray(item)) {
          for (var j = 0; j < item.length; j++) { out.push(item[j]); }
        } else {
          out.push(item);
        }
      }
      return out;
    };
  }

  // Array.prototype.at (Chrome 92)
  if (typeof Array.prototype.at !== 'function') {
    Array.prototype.at = function (index) {
      index = index >> 0;
      if (index < 0) { index += this.length; }
      return (index >= 0 && index < this.length) ? this[index] : undefined;
    };
  }

  // String.prototype.replaceAll (Chrome 85)
  if (typeof String.prototype.replaceAll !== 'function') {
    String.prototype.replaceAll = function (search, replacement) {
      var str = String(this);
      if (typeof search === 'string') {
        return str.split(search).join(replacement);
      }
      if (search instanceof RegExp) {
        if (!search.global) {
          throw new TypeError('replaceAll must be called with a global RegExp');
        }
        return str.replace(search, replacement);
      }
      return str.replace(search, replacement);
    };
  }

  // Promise.prototype.finally (Chrome 63)
  if (typeof Promise !== 'undefined' && typeof Promise.prototype.finally !== 'function') {
    Promise.prototype.finally = function (onFinally) {
      var P = this.constructor;
      return this.then(
        function (value) { return P.resolve(onFinally()).then(function () { return value; }); },
        function (reason) { return P.resolve(onFinally()).then(function () { throw reason; }); }
      );
    };
  }

  // AbortController / AbortSignal (Chrome 66). Minimal shim: Chrome 49's fetch
  // ignores the `signal` option, but the app constructs and aborts controllers
  // to cancel in-flight work, so the objects must exist and be abortable.
  if (typeof global.AbortController === 'undefined') {
    function AbortSignalShim() {
      this.aborted = false;
      this._listeners = [];
    }
    AbortSignalShim.prototype.addEventListener = function (type, fn) {
      if (type === 'abort' && this._listeners.indexOf(fn) === -1) { this._listeners.push(fn); }
    };
    AbortSignalShim.prototype.removeEventListener = function (type, fn) {
      if (type === 'abort') {
        var i = this._listeners.indexOf(fn);
        if (i !== -1) { this._listeners.splice(i, 1); }
      }
    };
    AbortSignalShim.prototype._dispatch = function () {
      for (var i = 0; i < this._listeners.length; i++) { this._listeners[i](); }
    };
    global.AbortSignal = AbortSignalShim;

    function AbortControllerShim() {
      this.signal = new AbortSignalShim();
    }
    AbortControllerShim.prototype.abort = function () {
      if (this.signal.aborted) { return; }
      this.signal.aborted = true;
      this.signal._dispatch();
    };
    global.AbortController = AbortControllerShim;
  }
})(typeof window !== 'undefined' ? window : this);
