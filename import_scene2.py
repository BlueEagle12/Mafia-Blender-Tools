bl_info = {
    "name": "Mafia Scene2.bin Importer",
    "author": "Blue Eagle",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > Mafia Scene2 (.bin)",
    "category": "Import-Export",
}

import os
import struct
import bpy
from mathutils import Quaternion, Matrix, Vector
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

try:
    from .import_4ds import The4DSImporter
except ImportError:
    from import_4ds import The4DSImporter

# Subclass that conditionally skips armature build on non-uniform scaling
class Scene2Importer(The4DSImporter):
    def build_armature(self):
        try:
            super().build_armature()
        except NotImplementedError as e:
            if "Non-uniform armature scaling" in str(e):
                print(f"Scene2Importer: skipping armature build due to non-uniform scale ({e})")
                return
            raise

class Scene2Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    maps_folder: StringProperty(
        name="Mafia Root Folder",
        subtype='DIR_PATH',
        default="",
        description="This will be your Mafia Root Folder."
    )

    def draw(self, context):
        self.layout.prop(self, "maps_folder")




class ImportScene2(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.scene2"
    bl_label = "Import Scene2.bin"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = "scene2.bin"
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def read_header(self, f):
        raw = f.read(6)
        return struct.unpack('<HI', raw)

    def read_cstr(self, f):
        data = bytearray()
        while True:
            b = f.read(1)
            if not b or b == b'\x00': break
            data += b
        try:
            return data.decode('utf-8')
        except:
            return data.decode('cp1250', errors='ignore')

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        # Prepare search directories: maps_folder and folder of the .bin file
        maps_dir = bpy.path.abspath(prefs.maps_folder) if prefs.maps_folder else None
        import_dir = os.path.dirname(self.filepath)
        search_dirs = [d for d in (maps_dir, import_dir) if d]

        def find_mesh(model_name):
            # direct lookup
            for sd in search_dirs:
                candidate = os.path.join(sd, model_name)
                if os.path.isfile(candidate):
                    return candidate
            # recursive search
            for sd in search_dirs:
                for root, _, files in os.walk(sd):
                    for f in files:
                        if f.lower() == model_name.lower():
                            return os.path.join(root, f)
            return None

        scene = context.scene


        with open(self.filepath, 'rb') as f:
            top_type, top_size = self.read_header(f)

            parsed_objects = []

            def parse_chunk(start, end):
                ptr = start
                while ptr + 6 <= end:
                    f.seek(ptr)
                    htype, hsize = self.read_header(f)
                    data_start = ptr + 6
                    data_end = ptr + hsize

                    if htype in (0x4000, 0xAE20):
                        parse_chunk(data_start, data_end)

                    elif htype in (0x4010, 0xAE21):
                        props_ptr = data_start
                        obj = {'pos': None, 'rot': None,'scale': None, 'model': None}

                        while props_ptr + 6 <= data_end:
                            f.seek(props_ptr)
                            ptype, psize = self.read_header(f)
                            dstart = props_ptr + 6

                            if ptype in (0x0010, 0xAE23):
                                f.seek(dstart)
                                obj['name'] = self.read_cstr(f)
                            elif ptype == 0x2012:
                                f.seek(dstart)
                                m = self.read_cstr(f).lower().replace('.i3d', '.4ds')
                                obj['model'] = m
                            elif ptype == 0x0020:
                                f.seek(dstart)
                                pos = struct.unpack('<3f', f.read(12))
                                obj['pos'] = (pos[0],pos[2],pos[1])
                            elif ptype == 0x002d:
                                f.seek(dstart)
                                scale = struct.unpack('<3f', f.read(12))
                                obj['scale'] = (scale[0],scale[2],scale[1])
                            elif ptype == 0x4020:
                                f.seek(dstart)
                                obj['parent'] = struct.unpack('<H', f.read(2))[0]
                            elif ptype == 0x0022:
                                f.seek(dstart)
                                q = struct.unpack('<4f', f.read(16))
                                quat = Quaternion((q[0], q[1], q[3], q[2]))
                                obj['rot'] = quat.to_euler('XYZ')
                                obj['quat'] = quat

                            props_ptr += psize


                        #frame_index = len(parsed_objects)
                        parsed_objects.append(obj)

                        if obj.get('model'):
                            mesh_path = find_mesh(obj['model'])
                            if not mesh_path:
                                self.report({'WARNING'}, f"Missing mesh: {obj['model']}")
                            else:


                                scale_mat = Matrix.Diagonal(obj['scale']).to_4x4()
                                rot_mat = Quaternion(obj['quat']).to_matrix().to_4x4()
                                trans_mat = Matrix.Translation(obj['pos'])

                                transform_mat = trans_mat @ rot_mat @ scale_mat
                                
                                obj['localTransform'] = transform_mat

                                before_objs = set(scene.objects)
                                imp = Scene2Importer(mesh_path)

                                dir_path = os.path.dirname(mesh_path)  # Parent directory
                                parent_dir = os.path.basename(dir_path).lower()  # e.g., "models" or "Intro"
                                grandparent_path = os.path.dirname(dir_path)  # Grandparent directory
                                grandparent_dir = os.path.basename(grandparent_path).lower()  # e.g., "Mafia" or "missions"

                                if parent_dir == "models":
                                    imp.base_dir = grandparent_path  # Two levels up: E:/Mafia
                                elif grandparent_dir == "missions":
                                    imp.base_dir = os.path.dirname(
                                        grandparent_path
                                    )  # Three levels up: E:/Mafia
                                else:
                                    # Fallback: assume two levels up (models-like structure)
                                    imp.base_dir = os.path.dirname(os.path.dirname(mesh_path))


                                imp.import_file()
                                new_objs = set(scene.objects) - before_objs
                                if not new_objs:
                                    self.report({'WARNING'}, f"No objects imported for {mesh_path}")
                                for new_obj in new_objs:
                                    # only apply transforms if it isn’t parented

                                    if new_obj.parent is None:
                                        empty = bpy.data.objects.new(obj['name'] + "_root", None)
                                        new_obj.parent = empty
                                        new_obj['base'] = empty

                                        empty.location        = obj['pos']
                                        empty.scale           = obj['scale']
                                        empty.rotation_euler  = obj['rot']

                                        if 'bpy_objs' not in obj:
                                            obj['bpy_objs'] = []
                                        obj['bpy_objs'].append(empty)

                    ptr += hsize

            parse_chunk(6, top_size)

        print("\n--- Scene2 Parenting Results ---")


        for idx, obj in enumerate(parsed_objects):
            print(f"Object: {obj['model']} ")

        for idx, obj in enumerate(parsed_objects):
            if 'parent' in obj and obj['parent'] != 0xFFFF:

                print(f"Object: {obj['name']} | Parent Index: {obj['parent']}")

                try:
                    parent_objs = parsed_objects[obj['parent']].get('bpy_objs', [])
                    child_objs = obj.get('bpy_objs', [])

                    if parent_objs and child_objs:
                        for child in child_objs:
                            child.parent = parent_objs[0]
                except IndexError:
                    self.report({'WARNING'}, f"Invalid parent index {obj['parent']} for object {idx}")

        return {'FINISHED'}

def menu_func_import(self, context):
    self.layout.operator(ImportScene2.bl_idname, text="Mafia Scene2 (.bin)")

def register():
    bpy.utils.register_class(Scene2Prefs)
    bpy.utils.register_class(ImportScene2)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportScene2)
    bpy.utils.unregister_class(Scene2Prefs)

if __name__ == "__main__":
    register()
