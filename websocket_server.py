# WebSocket server for Blender
# Version 0.1.0
# Copyright 2015 Jonathan Giroux (Bloutiouf)
# Licensed under MIT (http://opensource.org/licenses/MIT)

bl_info = {
    "name": "WebSocket server",
    "author": "Jonathan Giroux (Bloutiouf)",
    "version": (0, 1, 0),
    "blender": (2, 69, 0),
    "description": "Send Blender's state over a WebSocket connection.",
    "category": "Import-Export"
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, USERPREF_HT_header, WindowManager

import copy
import json
import mathutils
import queue
import threading

from wsgiref.simple_server import make_server
from ws4py.websocket import WebSocket as _WebSocket
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication

class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        # print(type(obj))
        
        if isinstance(obj, bpy.types.BlendData):
            return {
                "objects": list(self.default(object) for object in obj.objects)
            }
            
        if isinstance(obj, bpy.types.Camera):
            return {
                "angle": obj.angle
            }
            
        if isinstance(obj, bpy.types.Mesh):
            return None
            
        if isinstance(obj, bpy.types.Object):
            rotation = obj.rotation_euler
            if obj.rotation_mode == 'AXIS_ANGLE':
                rotation = list(obj.rotation_axis_angle)
            elif obj.rotation_mode == 'QUATERNION':
                rotation = obj.rotation_quaternion
            r = {
                "location": self.default(obj.location),
                "rotation": self.default(rotation),
                "rotationMode": obj.rotation_mode,
                "scale": self.default(obj.scale),
                "type": obj.type
            }
            if obj.data:
                r["data"] = obj.data.name
            return r
            
        if isinstance(obj, bpy.types.PointLamp):
            return {
                "color": self.default(obj.color),
                "power": obj.energy * 8 + 10,
                "type": obj.type
            }
            
        if isinstance(obj, bpy.types.Scene):
            return {
                "camera": obj.camera.name if obj.camera else None
            }
            
        if isinstance(obj, bpy.types.SpotLamp):
            return {
                "angle": obj.spot_size / 2,
                "blend": obj.spot_blend,
                "color": self.default(obj.color),
                "power": obj.energy * 8 + 10,
                "type": obj.type
            }
            
        if isinstance(obj, bpy.types.SunLamp):
            return {
                "color": self.default(obj.color),
                "power": obj.energy * 8 + 10,
                "type": obj.type
            }
            
        if isinstance(obj, bpy.types.World):
            r = {
                "ambiantColor": self.default(obj.ambiant_color),
                "ambientOcclusionBlendType": obj.light_settings.ao_blend_type,
                "ambientOcclusionFactor": obj.light_settings.ao_factor,
                "colorRange": obj.color_range,
                "environmentColor": obj.light_settings.environment_color,
                "environmentEnergy": obj.light_settings.environment_energy,
                "exposure": obj.exposure,
                "falloffStrength": obj.light_settings.falloff_strength,
                "gatherMethod": obj.gather_method,
                "horizonColor": self.default(obj.horizon_color),
                "indirectBounces": obj.light_settings.environment_bounces,
                "indirectFactor": obj.light_settings.environment_factor,
                "useAmbientOcclusion": obj.light_settings.use_ambient_occlusion,
                "useEnvironmentLighting": obj.light_settings.use_environment_light,
                "useFalloff": obj.light_settings.use_falloff,
                "useIndirectLighting": obj.light_settings.use_indirect_light,
                "useMist": obj.mist_settings.use_mist,
                "useSkyBlend": obj.use_sky_blend,
                "useSkyPaper": obj.use_sky_paper,
                "useSkyReal": obj.use_sky_real,
                "zenithColor": self.default(obj.zenith_color),
            }
            if obj.gather_method == "RAYTRACE":
                r["samples"] = obj.light_settings.samples
                r["samplingMethod"] = obj.light_settings.sample_method
                r["distance"] = obj.light_settings.distance
            if obj.gather_method == "APPROXIMATE":
                r["correction"] = obj.light_settings.correction
                r["errorThreshold"] = obj.light_settings.error_threshold
                r["passes"] = obj.light_settings.passes
                r["useCache"] = obj.light_settings.use_cache
            if obj.mist_settings.use_mist:
                r["mist"] = 2
            return r
            
        if isinstance(obj, bpy.types.TimelineMarker):
            return {
                "frame": obj.frame,
                "name": obj.name
            }
            
        if isinstance(obj, mathutils.Color):
            return list(obj)
            
        if isinstance(obj, mathutils.Euler):
            return list(obj)
            
        if isinstance(obj, mathutils.Quaternion):
            return list(obj)
            
        if isinstance(obj, mathutils.Vector):
            return list(obj)
            
        return json.JSONEncoder.default(self, obj)

def stringify(data):
    return JSONEncoder(separators=(",", ":")).encode(data)
    
previous_context = {}
previous_data_keys = {}
previous_scenes = {}

def get_context(addon_prefs, diff):
    global previous_context
    
    current_context = {
        "filePath": bpy.data.filepath,
        "selectedObjects": hasattr(bpy.context, "selected_objects") and list(object.name for object in bpy.context.selected_objects)
    }
    
    if previous_context == current_context and diff:
        return
        
    previous_context = current_context
    return current_context

def get_data(addon_prefs, diff):
    global previous_data_keys
    
    data = {}
    
    def fill(name, collection):
        if collection.is_updated or not diff:
            data[name] = {}
            if name in previous_data_keys:
                for n in previous_data_keys[name]:
                    if n not in collection:
                        data[name][n] = None
            for obj in collection:
                if obj.is_updated or not diff:
                    data[name][obj.name] = obj
            previous_data_keys[name] = collection.keys()
            if len(data[name]) == 0 and diff:
                del data[name]
    
    if 'CAMERAS' in addon_prefs.data_to_send:
        fill("cameras", bpy.data.cameras)
    if 'LAMPS' in addon_prefs.data_to_send:
        fill("lamps", bpy.data.lamps)
    if 'OBJECTS' in addon_prefs.data_to_send:
        fill("objects", bpy.data.objects)
    if 'WORLDS' in addon_prefs.data_to_send:
        fill("worlds", bpy.data.worlds)
    
    if len(data) == 0 and diff:
        return
        
    return data

def get_scene(scene, addon_prefs, diff):
    global previous_scenes
    previous_scene = previous_scenes.get(scene.name, None)
    
    current_scene = {
        "activeObject": scene.objects.active and scene.objects.active.name,
        "camera": scene.camera and scene.camera.name,
        "fps": scene.render.fps / scene.render.fps_base,
        "frame": scene.frame_current,
        "frameEnd": scene.frame_end,
        "frameStart": scene.frame_start,
        "gravity": scene.gravity,
        "objects": list(object.name for object in scene.objects),
        "timelineMarkers": list(scene.timeline_markers),
        "world": scene.world and scene.world.name
    }
    
    if previous_scene == current_scene and diff:
        return
        
    previous_scenes[scene.name] = current_scene
    return current_scene

def broadcast(sockets, message):
    for socket in sockets:
        socket.send(message)

def send_state(sockets):
    addon_prefs = bpy.context.user_preferences.addons[__name__].preferences
    
    broadcast(sockets, stringify(("app", {
        "version": bpy.app.version,
        "versionString": bpy.app.version_string
    })))
    
    data = get_data(addon_prefs, False)
    if data:
        broadcast(sockets, stringify(("data", data)))
    
    if 'SCENES' in addon_prefs.data_to_send:
        for scene in bpy.data.scenes:
            data = get_scene(scene, addon_prefs, False)
            if data:
                broadcast(sockets, stringify(("scene", scene.name, data)))
    
    if 'CONTEXT' in addon_prefs.data_to_send:
        data = get_context(addon_prefs, False)
        if data:
            broadcast(sockets, stringify(("context", data)))

message_queue = queue.Queue()
sockets = []

class WebSocketApp(_WebSocket):
    def opened(self):
        send_state([self])
        sockets.append(self)
        
    def closed(self, code, reason=None):
        sockets.remove(self)
        
    def received_message(self, message):
        data = json.loads(message.data.decode(message.encoding))
        message_queue.put(data)
    
@persistent
def load_post():
    send_state(sockets)

@persistent
def scene_update_post(scene):
    addon_prefs = bpy.context.user_preferences.addons[__name__].preferences
    
    data = get_data(addon_prefs, True)
    if data:
        broadcast(sockets, stringify(("data", data)))
    
    if 'SCENES' in addon_prefs.data_to_send:
        scene_diff = set(previous_scenes.keys()) - set(bpy.data.scenes.keys())
        for scene in scene_diff:
            broadcast(sockets, stringify(("scene", scene)))
            del previous_scenes[scene]
        
        data = get_scene(scene, addon_prefs, True)
        if data:
            broadcast(sockets, stringify(("scene", scene.name, data)))
    
    if 'CONTEXT' in addon_prefs.data_to_send:
        data = get_context(addon_prefs, True)
        if data:
            broadcast(sockets, stringify(("context", data)))
    
    while not message_queue.empty():
        data = message_queue.get()
        if data[0] == "scene" and data[1] in bpy.data.scenes:
            scene = bpy.data.scenes[data[1]]
            diff = data[2]
            if "frame" in diff:
                scene.frame_current = diff["frame"]
              
wserver = None

def start_server(host, port):
    global wserver
    if wserver:
        return False
    
    wserver = make_server(host, port,
        server_class=WSGIServer,
        handler_class=WebSocketWSGIRequestHandler,
        app=WebSocketWSGIApplication(handler_cls=WebSocketApp)
    )
    wserver.initialize_websockets_manager()
    
    wserver_thread = threading.Thread(target=wserver.serve_forever)
    wserver_thread.daemon = True
    wserver_thread.start()
    
    bpy.app.handlers.load_post.append(load_post)
    bpy.app.handlers.scene_update_post.append(scene_update_post)
    
    return True

def stop_server():
    global wserver
    if not wserver:
        return False
        
    wserver.shutdown()
    for socket in sockets:
        socket.close()
        
    wserver = None
    
    bpy.app.handlers.load_post.remove(load_post)
    bpy.app.handlers.scene_update_post.remove(scene_update_post)
    
    return True


class WebSocketServerSettings(AddonPreferences):
    bl_idname = __name__
    
    auto_start = BoolProperty(
        name="Start automatically",
        description="Automatically start the server when loading the add-on",
        default=True
    )
    
    host = StringProperty(
        name="Host",
        description="Listen on host:port",
        default="localhost"
    )
    
    port = IntProperty(
        name="Port",
        description="Listen on host:port",
        default=8137,
        min=0,
        max=65535,
        subtype="UNSIGNED"
    )
    
    data_to_send = EnumProperty(
        items=[
            ('ACTIONS', "Actions", "Action data"),
            ('ARMATURES', "Armatures", "Armature data"),
            ('BRUSHES', "Brushes", "Brush data"),
            ('CAMERAS', "Cameras", "Camera data"),
            ('CONTEXT', "Context", "Context data"),
            ('CURVES', "Curves", "Curve data"),
            ('FONTS', "Fonts", "Font data"),
            ('GREASE_PENCILS', "Grease pencils", "Grease pencil data"),
            ('IMAGES', "Images", "Image data"),
            ('LAMPS', "Lamps", "Lamp data"),
            ('MASKS', "Masks", "Mask data"),
            ('MATERIALS', "Materials", "Material data"),
            ('MESHES', "Meshes", "Mesh data"),
            ('METABALLS', "Metaballs", "Metaball data"),
            ('MOVIECLIPS', "Movieclips", "Movieclip data"),
            ('NODE_TREES', "Node trees", "Node tree data"),
            ('OBJECTS', "Objects", "Object data"),
            ('PARTICLES', "Particles", "Particle data"),
            ('SCENES', "Scenes", "Scene data"),
            ('SCREENS', "Screens", "Screen data"),
            ('SHAPE_KEYS', "Shape keys", "Shape key data"),
            ('SOUNDS', "Sounds", "Sound data"),
            ('SPEAKERS', "Speakers", "Speaker data"),
            ('TEXTURES', "Textures", "Texture data"),
            ('WORLDS', "Worlds", "World data")
        ],
        name="Data to send",
        description="Specify which data are sent to the clients",
        default={'OBJECTS', 'SCENES'},
        options={'ENUM_FLAG'}
    )
        
    def draw(self, context):
        layout = self.layout
        
        row = layout.row()
        split = row.split(percentage=0.3)
        
        col = split.column()
        col.prop(self, "host")
        col.prop(self, "port")
        col.separator()
        
        col.prop(self, "auto_start")
        
        if wserver:
            col.operator(Stop.bl_idname, icon='QUIT', text="Stop server")
        else:
            col.operator(Start.bl_idname, icon='QUIT', text="Start server")
            
        col = split.column()
        col.label("Data to send:", icon='RECOVER_LAST')
        col.prop(self, "data_to_send", expand=True)

class Start(Operator):
    """Start WebSocket server"""
    bl_idname = "websocket_server.start"
    bl_label = "Start WebSocket server"
    
    def execute(self, context):
        addon_prefs = context.user_preferences.addons[__name__].preferences
        if not start_server(str(addon_prefs.host), int(addon_prefs.port)):
            self.report({"ERROR"}, "The server is already started.")
            return {"CANCELLED"}
        return {"FINISHED"}

class Stop(Operator):
    """Stop WebSocket server"""
    bl_idname = "websocket_server.stop"
    bl_label = "Stop WebSocket server"
    
    def execute(self, context):
        if not stop_server():
            self.report({"ERROR"}, "The server is not started.")
            return {"CANCELLED"}
        return {"FINISHED"}
    
def register():
    bpy.utils.register_module(__name__)
    
    addon_prefs = bpy.context.user_preferences.addons[__name__].preferences
    if bool(addon_prefs.auto_start):
        start_server(str(addon_prefs.host), int(addon_prefs.port))

def unregister():
    stop_server()
    bpy.utils.unregister_module(__name__)
    
if __name__ == "__main__":
    register()
