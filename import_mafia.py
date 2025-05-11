# =====================================
#  Mafia Shared Importer - Blender Add-on
# =====================================

import os
import bpy
import bmesh
import gc
import math
from bpy.props import StringProperty, IntProperty
from bpy_extras.io_utils import ImportHelper

# -- Add-on Info --
bl_info = {
    "name": "Mafia Import Shared",
    "author": "Blue Eagle",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > Mafia (.bin)",
    "category": "Import-Export",
}

# -- Constants --
LIGHT_TYPES = {
    0x01: 'POINT',
    0x02: 'SPOT',
    0x03: 'SUN',
    0x04: 'AREA',
    0x05: 'POINT',
    0x06: 'POINT',
    0x08: 'AREA',
}


# SpecialObjectType values
OBJ_NONE            = 0x00
OBJ_PHYSICAL        = 0x23
OBJ_PLAYER          = 0x02
OBJ_CHARACTER       = 0x1B
OBJ_CAR             = 0x04
OBJ_DOOR            = 0x06
OBJ_DOG             = 0x15
OBJ_PUMPER          = 0x19
OBJ_PUBLIC_VEHICLE  = 0x08
OBJ_SCRIPT_SPECIAL  = 0x05

OBJ_NONE            = 0x00
OBJ_LIGHT           = 0x02
OBJ_CAMERA          = 0x03
OBJ_SOUND           = 0x04
OBJ_MODEL           = 0x09
OBJ_OCCLUDER        = 0x0C
OBJ_SECTOR          = 0x99
OBJ_LIGHTMAP        = 0x9A
OBJ_SCRIPT          = 0x9B

OBJECT_TYPE_ITEMS = [
    ('MODEL',    "Model", ""),
    ('LIGHT',    "Light", ""),
    ('CAMERA',   "Camera", ""),
    ('SOUND',    "Sound", ""),
    ('OCCLUDER', "Occluder", ""),
    ('SECTOR',   "Sector", ""),
    ('LIGHTMAP', "Lightmap", ""),
    ('SCRIPT',   "Script", ""),
]

# SpecialObjectType entries
SPECIAL_TYPE_ITEMS = [
    ('PHYSICAL',        "Physical", ""),
    ('PLAYER',          "Player", ""),
    ('CHARACTER',       "Character", ""),
    ('CAR',             "Car", ""),
    ('DOOR',            "Door", ""),
    ('DOG',             "Dog", ""),
    ('PUMPER',          "Pumper", ""),
    ('PUBLIC_VEHICLE',  "Public Vehicle", ""),
    ('SCRIPT_SPECIAL',  "Script (Special)", ""),
]

object_type_map = {
    'MODEL': OBJ_MODEL,
    'LIGHT': OBJ_LIGHT,
    'CAMERA': OBJ_CAMERA,
    'SOUND': OBJ_SOUND,
    'OCCLUDER': OBJ_OCCLUDER,
    'SECTOR': OBJ_SECTOR,
    'LIGHTMAP': OBJ_LIGHTMAP,
    'SCRIPT': OBJ_SCRIPT,
}

special_type_map = {
    'PHYSICAL':        OBJ_PHYSICAL,
    'PLAYER':          OBJ_PLAYER,
    'CHARACTER':       OBJ_CHARACTER,
    'CAR':             OBJ_CAR,
    'DOOR':            OBJ_DOOR,
    'DOG':             OBJ_DOG,
    'PUMPER':          OBJ_PUMPER,
    'PUBLIC_VEHICLE':  OBJ_PUBLIC_VEHICLE,
    'SCRIPT_SPECIAL':  OBJ_SCRIPT_SPECIAL,
}


# -- References --
try:
    from .import_4ds import The4DSImporter
except ImportError:
    from import_4ds import The4DSImporter

try:
    from .import_scene2 import Scene2Importer
except ImportError:
    from import_scene2 import Scene2Importer

try:
    from .import_cache import CacheBinImporter
except ImportError:
    from import_cache import CacheBinImporter



# -- Preferences Panel --
class MafiaPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    maps_folder: StringProperty(
        name="Mafia Root Folder",
        subtype='DIR_PATH',
        default="",
        description="Root folder for .4DS files"
    )  # type: ignore

    batch_size: IntProperty(
        name="Batch Size",
        description="How many objects to import per batch",
        default=500,
        min=1,
        max=10000
    )  # type: ignore

    debug_logging: bpy.props.BoolProperty(
        name="Enable Debug Logging",
        default=False,
        description="print detailed import debug information"
    )  # type: ignore

    def draw(self, context):
        self.layout.prop(self, "maps_folder")
        self.layout.prop(self, "batch_size")
        self.layout.prop(self, "debug_logging")

def print_debug(error):
    prefs = bpy.context.preferences.addons[__name__].preferences
    if prefs.debug_logging:
        print(error)    

# -- 4DS Importer Wrapper --
class Mafia_Importer(The4DSImporter):
    def build_armature(self):
        try:
            super().build_armature()
        except NotImplementedError as e:
            if "Non-uniform armature scaling" in str(e):
                print_debug(f"[SKIP] Skipping armature due to non-uniform scale: {e}")
                return
            raise

# -- Globals used in import batching --
to_link = []
instance_queue = []
GLOBAL_SUN_POWER = 1.0
GLOBAL_LIGHT_POWER = 100.0

# -- Class: .Bin Importer --
class ImportMafiaBIN(bpy.types.Operator, ImportHelper):
    bl_idname = "import_mafia.bin"
    bl_label = "Import Mafia .bin"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".bin"
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})


    light_power: bpy.props.FloatProperty(
    name="Light Power",
    default=100.0,
    min=0.0,
    max=10000.0,
    description="Power value for imported lights"
    ) # type: ignore

    sun_power: bpy.props.FloatProperty(
    name="Sun Power",
    default=5.0,
    min=0.0,
    max=10000.0,
    description="Power value for imported sun(s)"
    ) # type: ignore

    filter_object_types: bpy.props.EnumProperty(
        name="General Types",
        items=OBJECT_TYPE_ITEMS,
        options={'ENUM_FLAG'},
        default={'MODEL', 'LIGHT', 'SECTOR', 'OCCLUDER'},
        description="Importable object types"
    ) # type: ignore

    filter_special_types: bpy.props.EnumProperty(
        name="Special Types",
        items=SPECIAL_TYPE_ITEMS,
        options={'ENUM_FLAG'},
        default={'PHYSICAL', 'CAR', 'PUBLIC_VEHICLE'},
        description="Importable special object types"
    ) # type: ignore

    def execute(self, context):
        name = os.path.basename(self.filepath).lower()

        global GLOBAL_SUN_POWER, GLOBAL_LIGHT_POWER
        GLOBAL_SUN_POWER = self.sun_power
        GLOBAL_LIGHT_POWER = self.light_power



        if name == "scene2.bin":
            importer = Scene2Importer(self.filepath,start_import_timer)
            importer.operator = self
        elif name == "cache.bin":
            importer = CacheBinImporter(self.filepath,start_import_timer)
            importer.operator = self
        else:
            self.report({'ERROR'}, "Only 'scene2.bin' and 'cache.bin' are supported.")
            return {'CANCELLED'}

        return importer.run(context)
    
    def draw(self, context):
        self.layout.prop(self, "light_power")
        self.layout.prop(self, "sun_power")
        col = self.layout.column()
        col.label(text="Object Types:")
        col.prop_menu_enum(self, "filter_object_types", text="General Types")

        col.separator()

        col.label(text="Special Types:")
        col.prop_menu_enum(self, "filter_special_types", text="Special Types")

def menu_func(self, context):
    self.layout.operator(
        ImportMafiaBIN.bl_idname,
        text="Mafia Cache, Scene2 (.bin)"
    )


# -- Utility: Get or create collection --
def getCollection(collection, collection_name, parent=None):
    if collection:
        return collection

    collection_name = collection_name or '4DS_Collection'

    if collection_name in bpy.data.collections:
        collection = bpy.data.collections[collection_name]
    else:
        collection = bpy.data.collections.new(collection_name)

    link_target = parent or bpy.context.scene.collection

    if not any(c is collection for c in link_target.children):
        link_target.children.link(collection)

    return collection

# -- Begin Import (asynchronous, per-frame) --
def start_import_timer(operator_instance, on_complete=None, scene_name=None):
    wm = operator_instance.wm
    total = operator_instance.total
    scene_name = scene_name or "Collection"
    collection_name = f"{scene_name}"
    collection = getCollection(None, collection_name)

    instance_queue.clear()
    to_link.clear()
    reset_model_cache()

    wm.progress_begin(0, total)

    def timer_callback():
        return _step_import(operator_instance, on_complete, collection)

    bpy.context.preferences.edit.use_global_undo = False
    bpy.app.timers.register(timer_callback)
    return {'RUNNING_MODAL'}

# -- Finalize import and link all objects --
def end_import_timer():
    for collection, obj in to_link:
        try:
            if obj.name not in collection.objects:
                collection.objects.link(obj)
        except ReferenceError:
            print_debug(f"[WARN] Skipping freed object during linking")

    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    to_link.clear()
    gc.collect()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.view_layer.update()

# -- Per-frame import step --
def _step_import(self, on_complete=None, collection=None):
    if not self.queue:
        if on_complete:
            on_complete()
        end_import_timer()
        self.wm.progress_end()
        return None

    prefs = bpy.context.preferences.addons[__name__].preferences
    batch_size = prefs.batch_size
    enabled_types = set(object_type_map[k] for k in self.operator.filter_object_types if k in object_type_map)
    special_types = set(special_type_map[k] for k in self.operator.filter_special_types if k in special_type_map)


    for i in range(min(batch_size, len(self.queue))):
        task = self.queue.pop(0)
        done = self.total - len(self.queue)


        special_type = task.get('special_type')
        if special_type is None:
            special_type = 0x00

        object_type = task.get('obj_type')
        if object_type is None:
            object_type = 0x00


        print_debug(f"[TASK] obj_type={object_type}, special_type={special_type}")

        if object_type in enabled_types or (
            special_type in special_types
        ):
            if task['obj_type'] == OBJ_LIGHT:
                create_light(task, collection, self.parent_links)
            else:
                target_collection = getCollection(None, task.get('collection'), parent=collection)
                import_model(task, target_collection, self.name_to_empty, self.parent_links)

        self.wm.progress_update(done)

        if done % 200 == 0:
            gc.collect()

    return 0.01



# -- Import and instance 4DS model --
def import_model(obj, collection, name_to_empty, parent_links):
    prefs = bpy.context.preferences.addons[__name__].preferences
    maps_dir = bpy.path.abspath(prefs.maps_folder) if prefs.maps_folder else None
    search_dirs = [maps_dir] if maps_dir else []

    if not hasattr(import_model, "_cache"):
        import_model._cache = {}

    model_cache = import_model._cache
    model_name = obj.get('model')

    if not model_name:
        target_obj = bpy.data.objects.get(obj.get('name'))
        if target_obj:
            parent_name = obj.get('parent_name')
            if parent_name and parent_name != "Primary sector":
                print_debug(f"[SCENE] Parent Assigned {parent_name}")
                parent_links.append((target_obj, parent_name))

            target_obj.rotation_euler = obj.get('rot') or target_obj.rotation_euler
            target_obj.location = obj.get('pos') or target_obj.location
            target_obj.scale = obj.get('scale') or target_obj.scale

            if obj.get('hidden'):
                target_obj.hide_viewport = True
                target_obj.hide_render = True
        return

    cache_result = model_cache.get(model_name)
    empty = None

    if cache_result:
        print_debug(f"[INSTANCE] Instancing cached 4DS model: {model_name}")
        base_objects, empty_old = cache_result
        duplicates = []
        original_to_duplicate = {}

        for base in base_objects:

            data = base.data
            name = base.name
            dup = bpy.data.objects.new(name, data)
            original_to_duplicate[base] = dup
            if base is not empty_old:
                duplicates.append(dup)
            else:
                empty = dup
                to_link.append((collection, empty))

        for base, dup in original_to_duplicate.items():
            if base.parent and base.parent in original_to_duplicate:
                dup.parent = original_to_duplicate[base.parent]
                dup.matrix_basis = base.matrix_basis.copy()

    else:
        print_debug(f"[IMPORT] Loading new 4DS model: {model_name}")
        path = _find_mesh(model_name, search_dirs)
        if not path:
            print_debug(f"Missing mesh: {model_name}")
            return

        imp4ds = Mafia_Importer(path)
        duplicates = imp4ds.import_file()
        if not duplicates:
            print_debug(f"[SKIP] No importable objects found in 4DS model: {model_name}")
            return

    for new in duplicates:

        if new is not empty:
            to_link.append((collection, new))
            
            if obj['hidden']:
                new.hide_viewport = True
                new.hide_render = True
            if new.parent is None:
                if empty is None:
                    empty = bpy.data.objects.new(obj['name'] + "_root", None)
                    duplicates.append(empty)
                    to_link.append((collection, empty))

                new.matrix_parent_inverse = empty.matrix_world.inverted()
                new.parent = empty

    if empty:
        empty.location = obj['pos']
        empty.rotation_euler = obj['rot']
        empty.scale = obj['scale']

        if obj['name'] not in name_to_empty:
            name_to_empty[obj['name']] = empty

        parent = obj.get('parent_name')
        if parent and parent != "Primary sector":
            print_debug(f"Parent Assigned {parent}")
            parent_links.append((empty, parent))

        model_cache.setdefault(model_name, (duplicates, empty))

# -- Reset import model cache --
def reset_model_cache():
    if hasattr(import_model, "_cache"):
        import_model._cache.clear()

# -- Locate mesh file by name --
def _find_mesh(name, search_dirs):
    for d in search_dirs:
        f = os.path.join(d, name)
        if os.path.isfile(f):
            return f
    for d in search_dirs:
        for root, _, files in os.walk(d):
            for fi in files:
                if fi.lower() == name.lower():
                    return os.path.join(root, fi)
    return None

# -- Create Blender light from parsed object --
def create_light(lt, collection, parent_links):
    if 'light_type' not in lt:
        return

    code = lt.get('light_type')
    ltype = LIGHT_TYPES.get(code, 'POINT')
    name = ltype
    ld = bpy.data.lights.new(name=name, type=ltype)

    color = lt.get('color') or (1.0, 1.0, 1.0)
    ld.color = color

    power = lt.get('power')
    if ltype == "SUN":
        ld.energy = (power if power is not None else 250.0) * GLOBAL_SUN_POWER
    else:
        ld.energy = (power if power is not None else 250.0) * GLOBAL_LIGHT_POWER

    rng = lt.get('range')
    if rng is not None:
        ld.cutoff_distance = rng

    if ltype == "SPOT":
        angle = lt.get('angle')
        if angle is not None:
            ld.spot_size = angle

    lo = bpy.data.objects.new(name, ld)
    if lt.get('pos'):
        lo.location = lt['pos']
    if lt.get('rot'):
        lo.rotation_euler = lt['rot']
        lo.rotation_euler.x += math.radians(90)

    to_link.append((collection, lo))

    parent = lt.get('parent_name')
    if parent and parent != "Primary sector":
        print_debug(f"Parent Assigned {parent}")
        parent_links.append((lo, parent))

    return None

# =========================
# Wireframe Visibility Panel
# =========================

_wireframe_update_queue = []

def update_wireframe_visibility(self, context):
    global _wireframe_update_queue
    show = context.scene.show_wireframe_objs
    _wireframe_update_queue = [
        obj for obj in bpy.data.objects
        if obj.type == 'MESH' and obj.get("Mafia.wireframe") and obj.hide_viewport != (not show)
    ]
    bpy.app.timers.register(process_wireframe_queue, first_interval=0.01)

def process_wireframe_queue():
    global _wireframe_update_queue
    chunk_size = 100
    for _ in range(min(chunk_size, len(_wireframe_update_queue))):
        obj = _wireframe_update_queue.pop(0)
        obj.hide_viewport = not bpy.context.scene.show_wireframe_objs
    return 0.01 if _wireframe_update_queue else None

class VIEW3D_PT_wireframe_visibility(bpy.types.Panel):
    bl_label = "Mafia Sector Tools"
    bl_idname = "VIEW3D_PT_wireframe_visibility"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Display'

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "show_wireframe_objs")

def register_props():
    bpy.types.Scene.show_wireframe_objs = bpy.props.BoolProperty(
        name="Show Sector Objects",
        description="Toggle visibility of Mafia zone objects",
        default=True,
        update=update_wireframe_visibility
    )

def unregister_props():
    del bpy.types.Scene.show_wireframe_objs

classes = [VIEW3D_PT_wireframe_visibility]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_props()
    bpy.utils.register_class(MafiaPrefs)
    bpy.utils.register_class(ImportMafiaBIN)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_props()
    bpy.utils.unregister_class(MafiaPrefs)
    bpy.utils.unregister_class(ImportMafiaBIN)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
