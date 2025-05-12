
import os
from .helper import Util


class CacheBinImporter:
    def __init__(self, filepath, start_timer):
        self.filepath = filepath
        self.start_import_timer = start_timer

    def run(self, context):
        self.scene = context.scene
        self.wm = context.window_manager

        self.queue = self.parse_cache(self.filepath)
        self.total = len(self.queue)

        folder_name = os.path.basename(os.path.dirname(self.filepath))

        if not self.queue:
            print("[SKIP] No entities found in cache.bin")
            return {'CANCELLED'}

        return self.start_import_timer(self, on_complete=None, scene_name=folder_name)

    def parse_cache(self, path):
        props = []

        with open(path, 'rb') as f:
            _, total_size = Util.read_header(f)
            version = Util.read_int_32(f)

            ptr = f.tell()
            while ptr + 6 <= total_size - 4:
                f.seek(ptr)
                chunk_type, chunk_size = Util.read_header(f)

                object_name, name_len = Util.read_string32(f)
                bounds = f.read(0x4C)  # Bounding box or similar block

                header_size = 6 + 4 + name_len + 0x4C
                instance_start = f.tell()

                while f.tell() < instance_start + chunk_size - header_size:
                    inst_type, inst_size = Util.read_header(f)

                    model = Util.read_string32(f)[0].lower().replace('.i3d', '.4ds')

                    name = model.removesuffix('.i3d').removesuffix('.4ds')

                    pos    = Util.read_vector3(f, reorder=True)
                    rot    = Util.read_quat(f, reorder=True)
                    scale  = Util.read_vector3(f, reorder=True)
                    unk0   = Util.read_int_32(f)
                    scale2 = Util.read_vector3(f, reorder=True)

                    props.append({
                        'name': name,
                        'model': model,
                        'pos': pos,
                        'rot': rot.to_euler('XYZ'),
                        'scale': scale,
                        'scale2': scale2,
                        'unk0': unk0,
                        'obj_type': 0x09,  # Hardcoded as model
                        'hidden': None,
                        'collection': object_name,
                    })

                ptr += chunk_size

        return props