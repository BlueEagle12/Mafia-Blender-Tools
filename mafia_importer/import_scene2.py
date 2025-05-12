
import os
from .helper import Util

# === Chunk Types ===
CHUNK_ROOT_TYPES    = (0x4000, 0xAE20)
CHUNK_ELEMENT_TYPES = (0x4010, 0xAE21)

# === Property Constants ===
PROP_TYPE_NORMAL    = 0x4011
PROP_NAME           = 0x0010
PROP_NAME_SPECIAL   = 0xAE23
PROP_MODEL          = 0x2012
PROP_POSITION       = 0x0020
PROP_PARENT         = 0x4020
PROP_ROTATION       = 0x0022
PROP_SCALE          = 0x002D
PROP_HIDDEN         = 0x4033
PROP_LIGHT_MAIN     = 0x4040
PROP_TYPE_SPECIAL   = 0xAE22

LIGHT_TYPE          = 0x4041
LIGHT_COLOR         = 0x0026
LIGHT_POWER         = 0x4042
LIGHT_RANGE         = 0x4044
LIGHT_UNKNOWN       = 0x4043

# === Object Type Values ===
OBJ_NONE            = 0x00
OBJ_LIGHT           = 0x02
OBJ_CAMERA          = 0x03
OBJ_SOUND           = 0x04
OBJ_MODEL           = 0x09
OBJ_OCCLUDER        = 0x0C
OBJ_SECTOR          = 0x99
OBJ_LIGHTMAP        = 0x9A
OBJ_SCRIPT          = 0x9B


class Scene2Importer:
    def __init__(self, filepath, start_timer):
        self.filepath = filepath
        self.start_import_timer = start_timer

    def run(self, context):
        self.scene = context.scene
        self.wm = context.window_manager
        self.queue = self.parse_scene2(self.filepath)
        self.total = len(self.queue)

        folder_name = os.path.basename(os.path.dirname(self.filepath))

        if not self.queue:
            print("[SKIP] No entities found in scene2.bin")
            return {'CANCELLED'}

        return self.start_import_timer(self, on_complete=None, scene_name=folder_name)

    def parse_scene2(self, path):
        tasks = []
        with open(path, 'rb') as f:
            _, size = Util.read_header(f)
            self.recurse(f, 6, size, tasks)
        return tasks

    def recurse(self, f, start, end, tasks):
        ptr = start
        while ptr + 6 <= end:
            f.seek(ptr)
            ctype, csize = Util.read_header(f)
            dstart, dend = ptr + 6, ptr + csize

            if ctype in CHUNK_ROOT_TYPES:
                self.recurse(f, dstart, dend, tasks)

            elif ctype in CHUNK_ELEMENT_TYPES:
                ent = self.read_element_properties(f, dstart, dend)
                if ent:
                    tasks.append(ent)

            ptr += csize

    def get_parent_name(self, f, ptr, psize, props):
        sub_start = ptr + 6
        sub_end = ptr + psize
        scan = sub_start

        while scan + 6 <= sub_end:
            f.seek(scan)
            stype, ssize = Util.read_header(f)
            f.seek(scan + 6)

            if stype in (PROP_NAME, PROP_NAME_SPECIAL):
                props['parent_name'] = Util.read_terminated_string(f)
                return

            scan += ssize

    def read_element_properties(self, f, start, end):
        props = {
            'name': None, 'model': None, 'pos': None, 'rot': None, 'scale': None,
            'light_type': None, 'color': None, 'power': None, 'range': None, 'angle': None,
            'parent_name': None, 'hidden': None, 'obj_type': None, 'special_type': None,
        }

        ptr = start
        while ptr + 6 <= end:
            f.seek(ptr)
            property_id, psize = Util.read_header(f)
            f.seek(ptr + 6)

            if property_id == PROP_PARENT:
                self.get_parent_name(f, ptr, psize, props)

            elif property_id in (PROP_NAME, PROP_NAME_SPECIAL):
                props['name'] = Util.read_terminated_string(f)

            elif property_id == PROP_MODEL:
                props['model'] = Util.read_terminated_string(f).lower().replace('.i3d', '.4ds')

            elif property_id == PROP_POSITION:
                props['pos'] = Util.read_vector3(f, reorder=True)

            elif property_id == PROP_ROTATION:
                props['rot'] = Util.read_quat(f, reorder=True).to_euler('XYZ')

            elif property_id == PROP_SCALE:
                props['scale'] = Util.read_vector3(f, reorder=True)

            elif property_id == PROP_TYPE_NORMAL:
                props['obj_type'] = Util.read_int_32(f)

            elif property_id == PROP_TYPE_SPECIAL:
                props['special_type'] = Util.read_int_32(f)

            elif property_id == PROP_HIDDEN:
                props['hidden'] = True

            elif property_id == PROP_LIGHT_MAIN:
                self.read_light_properties(f, ptr + 6, ptr + psize, props)

            ptr += psize

        return props

    def read_light_properties(self, f, start, end, props):
        ptr = start
        while ptr + 6 <= end:
            f.seek(ptr)
            prop_id, psize = Util.read_header(f)
            f.seek(ptr + 6)

            if prop_id == LIGHT_TYPE:
                props['light_type'] = Util.read_int_32(f)
                props['obj_type'] = OBJ_LIGHT

            elif prop_id == LIGHT_COLOR:
                props['color'] = Util.read_vector3(f)

            elif prop_id == LIGHT_POWER:
                props['power'] = Util.read_float_32(f)

            elif prop_id == LIGHT_RANGE:
                _near = Util.read_float_32(f)
                far = Util.read_float_32(f)
                props['range'] = far

            elif prop_id == LIGHT_UNKNOWN:
                _unk1 = Util.read_float_32(f)
                angle = Util.read_float_32(f)
                props['angle'] = angle

            ptr += psize