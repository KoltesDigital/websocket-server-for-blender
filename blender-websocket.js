/*
 * WebSocket server for Blender
 * Version 0.1.0
 * Copyright 2015 Jonathan Giroux (Bloutiouf)
 * Licensed under MIT (http://opensource.org/licenses/MIT)
 */

BlenderWebSocket = (function() {
	function isObject(input) {
		return (Object.prototype.toString.call(input) === "[object Object]");
	};

	// recursive
	function merge(target) {
		for (var i = 1, n = arguments.length; i < n; ++i) {
			var arg = arguments[i];
			if (!isObject(arg)) continue;
			for (var prop in arg) {
				if (isObject(target[prop]) && isObject(arg[prop]))
					merge(target[prop], arg[prop]);
				else
					target[prop] = arg[prop];
			}
		}
		return target;
	}

	function BlenderWebSocket() {
		this.context = {};
		this.data = {};
		this.scenes = {};

		this.axes = new Array(3);
		this.connected = false;
		this.listeners = {};

		this.setAxes(""); // default axes
	}

	BlenderWebSocket.prototype.addListener = BlenderWebSocket.prototype.on = function(event, handler) {
		if (!this.listeners[event])
			this.listeners[event] = [handler];
		else
			this.listeners[event].push(handler);
	};

	BlenderWebSocket.prototype.close = function() {
		if (this.websocket)
			this.websocket.close(); // cleared in onclose
	};

	BlenderWebSocket.prototype.open = function(options) {
		if (this.websocket)
			return;

		var self = this;

		options = merge({
			url: "ws://localhost:8137/"
		}, options);

		this.context = {};
		this.data = {};
		this.scenes = {};

		var websocket = this.websocket = new WebSocket(options.url);

		var listeners = this.listeners;

		function emit(event) {
			var handlers = listeners[event];
			if (handlers) {
				var args = Array.prototype.slice.call(arguments, 1);
				handlers.forEach(function(handler) {
					handler.apply(null, args);
				});
			}
		}

		websocket.onclose = function() {
			if (self.connected)
				emit("close");
			self.connected = false;
			self.websocket = null;
		};

		websocket.onerror = emit.bind(this, "error");

		var axes = this.axes;

		function swapAxes(arr, offset) {
			offset = offset || 0;
			return arr.map(function swapAxesIter(v, i) {
				if (i < offset)
					return v;
				var axis = axes[i - offset];
				return arr[axis.index] * axis.scale;
			});
		}

		function swapAxesData(data) {
			if (data.objects) {
				for (var name in data.objects) {
					var obj = data.objects[name];
					if (!obj) continue;
					if (obj.location)
						obj.location = swapAxes(obj.location);
					if (obj.scale)
						obj.scale = swapAxes(obj.scale);
				}
			}
			return data;
		}

		function swapAxesScene(scene) {
			if (scene.gravity)
				scene.gravity = swapAxes(scene.gravity);
			return scene;
		}

		websocket.onmessage = function(event) {
			try {
				var data = JSON.parse(event.data);
			} catch(err) {
				emit("badFormat", event.data);
				return;
			}

			switch (data[0]) {
				case "app":
					if (!self.connected) {
						self.connected = true;
						emit("open", data[1]);
					}
					break;

				case "context":
					self.context = data[1];
					emit("context", self.context);
					break;

				case "data":
					var diff = swapAxesData(data[1]);
					for (var collection in diff) {
						if (!self.data.hasOwnProperty(collection))
							self.data[collection] = {};
						for (var name in diff[collection]) {
							var add = !self.data[collection][name];
							self.data[collection][name] = diff[collection][name];
							if (add)
								emit("add", collection, name);
						}
						for (var name in self.data[collection])
							if (diff[collection][name] === null) {
								emit("remove", collection, name);
								delete self.data[collection][name];
							}
					}
					emit("data", self.data, diff);
					break;

				case "scene":
					var name = data[1];
					if (!data[2]) {
						emit("remove", "scenes", name);
						delete self.scenes[name];
					} else {
						self.scenes[name] = swapAxesScene(data[2]);
						emit("add", "scenes", name);
					}
					emit("scene", name, self.scenes[name]);
					break;

				default:
					emit("unknownMessage", data);
					break;
			}
		};
	};

	BlenderWebSocket.prototype.removeListener = BlenderWebSocket.prototype.off = function(event, handler) {
		if (!this.listeners[event])
			return;
		var index = this.listeners[event].indexOf(handler);
		if (index !== -1)
			this.listeners[event].splice(index, 1);
	};

	BlenderWebSocket.prototype.setAxes = function(axes) {
		var lowerAxes = axes.toLowerCase();
		var indexes = "xyz";
		for (var i = 0; i < 3; ++i) {
			this.axes[i] = {
				index: (i < axes.length ? indexes.indexOf(lowerAxes[i]) : i),
				scale: (lowerAxes[i] === axes[i] ? 1 : -1)
			};
		}
	};

	BlenderWebSocket.prototype.setContext = function(context) {
		if (this.websocket)
			this.websocket.send(JSON.stringify(["context", context]));
	};

	BlenderWebSocket.prototype.setData = function(data) {
		if (this.websocket)
			this.websocket.send(JSON.stringify(["data", data]));
	};

	BlenderWebSocket.prototype.setScene = function(scene, diff) {
		if (this.websocket)
			this.websocket.send(JSON.stringify(["scene", scene, diff]));
	};

	return BlenderWebSocket;
})();
