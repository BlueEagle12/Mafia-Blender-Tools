import os
import struct
import bpy
import bmesh
from math import radians
from mathutils import Matrix, Vector
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from .helper import Util

# ----------------------------------
# File Version Constants
# ----------------------------------
VERSION_MAFIA     = 29
VERSION_HD2       = 41
VERSION_CHAMELEON = 42

# ----------------------------------
# Frame Type Constants
# ----------------------------------
FRAME_VISUAL     = 1
FRAME_LIGHT      = 2
FRAME_CAMERA     = 3
FRAME_SOUND      = 4
FRAME_SECTOR     = 5
FRAME_DUMMY      = 6
FRAME_TARGET     = 7
FRAME_USER       = 8
FRAME_MODEL      = 9
FRAME_JOINT      = 10
FRAME_VOLUME     = 11
FRAME_OCCLUDER   = 12
FRAME_SCENE      = 13
FRAME_AREA       = 14
FRAME_LANDSCAPE  = 15

# ----------------------------------
# Visual Type Constants
# ----------------------------------
VISUAL_OBJECT      = 0
VISUAL_LITOBJECT   = 1
VISUAL_SINGLEMESH  = 2
VISUAL_SINGLEMORPH = 3
VISUAL_BILLBOARD   = 4
VISUAL_MORPH       = 5
VISUAL_LENS        = 6
VISUAL_PROJECTOR   = 7
VISUAL_MIRROR      = 8
VISUAL_EMITOR      = 9
VISUAL_SHADOW      = 10
VISUAL_LANDPATCH   = 11


# ----------------------------------
# Material Constants
# ----------------------------------

MTL_DIFFUSETEX          = 0x00040000
MTL_COLORED             = 0x08000000
MTL_MIPMAP              = 0x00800000
MTL_ANIMTEXDIFF         = 0x04000000
MTL_ANIMTEXALPHA        = 0x02000000
MTL_DOUBLESIDED         = 0x10000000
MTL_ENVMAP              = 0x00080000
MTL_NORMTEXBLEND        = 0x00000100
MTL_MULTIPLYTEXBLEND    = 0x00000200
MTL_ADDTEXBLEND         = 0x00000400
MTL_CALCREFLECTTEXY     = 0x00001000
MTL_PROJECTREFLECTTEXY  = 0x00002000
MTL_PROJECTREFLECTTEXZ  = 0x00004000
MTL_ADDEFFECT           = 0x00008000
MTL_ALPHATEX            = 0x40000000
MTL_COLORKEY            = 0x20000000
MTL_ADDITIVEMIX         = 0x80000000


# ----------------------------------
# Fallbacks / Special Cases
# ----------------------------------
ALPHA_FALLBACK = ["9ker1.bmp"]  # Textures that require legacy alpha mapping fallback


def print_debug(error):
    prefs = bpy.context.preferences.addons['Mafia_Formats'].preferences
    if prefs.debug_logging:
        print(error)    


class The4DSImporter:
    def __init__(self, filepath):
        self.filepath = filepath

        dir_path = os.path.dirname(filepath)
        parent_dir = os.path.basename(dir_path).lower()
        grandparent_path = os.path.dirname(dir_path)
        grandparent_dir = os.path.basename(grandparent_path).lower()

        if parent_dir == "models":
            self.base_dir = grandparent_path
        elif grandparent_dir == "missions":
            self.base_dir = os.path.dirname(grandparent_path)
        else:
            self.base_dir = os.path.dirname(os.path.dirname(filepath))

        self.base_dir = os.path.normpath(self.base_dir)
        print_debug(f"Base directory set to: {self.base_dir}")

        self.version = 0
        self.materials = []
        self.skinned_meshes = []
        self.frames_map = {}
        self.frame_index = 1
        self.joints = []
        self.bone_nodes = {}
        self.base_bone_name = None
        self.bones_map = {}
        self.armature = None
        self.armature_scale_factor = None
        self.parenting_info = []
        self.frame_types = {}
        self.texture_cache = {}

    def parent_to_bone(self, obj, bone_name):
        if not self.armature or bone_name not in self.armature.data.bones:
            print_debug(f"[ERROR] Bone '{bone_name}' not found in armature")
            return

        obj.parent = self.armature
        obj.parent_type = 'BONE'
        obj.parent_bone = bone_name

        bone = self.armature.data.bones[bone_name]
        obj.matrix_world.translation = self.armature.matrix_world @ bone.head_local.to_3d()

        print_debug(f"[PARENT] {obj.name} parented to bone '{bone_name}' in armature '{self.armature.name}'")


    def get_color_key(self, filepath):
        """Extract normalized RGB color at palette index 0 from an 8-bit BMP."""
        try:
            with open(filepath, "rb") as f:
                f.seek(14)
                dib_size = Util.read_int_32(f)
                if dib_size != 40:
                    print_debug(f"[BMP] Unsupported DIB header size in '{filepath}'")
                    return None

                f.seek(36, 1)  # Skip ahead to palette start (offset 54)
                b, g, r, _ = struct.unpack("<BBBB", f.read(4))
                color_key = (r / 255.0, g / 255.0, b / 255.0)
                print_debug(f"[BMP] Color key from '{filepath}': {color_key}")
                return color_key

        except Exception as e:
            print_debug(f"[BMP] Failed to read color key from '{filepath}': {e}")
            return None

    

    def get_bmp_palette_and_indices(self, filepath):
        """Extract RGB palette and 2D pixel index data from an 8-bit indexed BMP."""
        palette = []
        indices = []

        try:
            with open(filepath, "rb") as f:
                f.seek(14)
                dib_size = Util.read_int_32(f)
                if dib_size != 40:
                    print_debug(f"[BMP] Unsupported DIB header size in '{filepath}'")
                    return None, None

                f.seek(10)
                pixel_data_offset = Util.read_int_32(f)

                f.seek(18)
                width = Util.read_int_32(f)
                height = Util.read_int_32(f)

                f.seek(28)
                bpp = Util.read_int_16(f)

                if bpp != 8:
                    print_debug(f"[BMP] Not an 8-bit indexed BMP: '{filepath}'")
                    return None, None

                # Read palette entries (BGRA, 4 bytes each)
                f.seek(54)
                num_colors = (pixel_data_offset - 54) // 4
                for _ in range(num_colors):
                    b, g, r, _ = struct.unpack("<BBBB", f.read(4))
                    palette.append((r, g, b))

                # Read pixel indices (bottom-up rows)
                row_size = ((width + 3) // 4) * 4  # 4-byte alignment
                f.seek(pixel_data_offset)

                for _ in range(height):
                    row_data = list(f.read(row_size))[:width]
                    indices.insert(0, row_data)  # BMP rows are stored bottom-up

                return palette, indices

        except Exception as e:
            print_debug(f"[BMP] Failed to read palette from '{filepath}': {e}")
            return None, None


    def create_alpha_image(self, filepath, transparent_index, image_name="AlphaMask"):

        palette, indices = self.get_bmp_palette_and_indices(filepath)

        if indices:
            height = len(indices)
            width = len(indices[0])

            image = bpy.data.images.new(name=image_name, width=width, height=height, alpha=True)
            pixels = []

            for row in reversed(indices):
                for index in row:
                    val = 0.0 if index == transparent_index else 1.0
                    pixels.extend([val, val, val, 1.0])

            image.pixels = pixels
            image.pack()
            return image
        else:
            return False


    def get_or_load_texture(self, filepath):
        norm_path = os.path.normpath(filepath.lower())

        if norm_path in self.texture_cache:
            print_debug(f"Reused texture from cache: {filepath}")
            return self.texture_cache[norm_path]

        try:
            image = bpy.data.images.load(filepath, check_existing=True)
            self.texture_cache[norm_path] = image
            print_debug(f"Loaded texture: {filepath}")
        except Exception as e:
            print_debug(f"Warning: Failed to load texture {filepath}: {e}")
            self.texture_cache[norm_path] = None  # Avoid retrying failed loads

        return self.texture_cache[norm_path]



    def get_material_template(self, template_type, nodes, links, tex_path=None, alpha_path=None, color_key=None, alpha_map=None, emission_strength=0.0, env_tex=None, metallic=0.0):
        nodes.clear()

        if template_type == "SKY_ATMOSPHERE" and tex_path:
            tex_image = nodes.new("ShaderNodeTexImage")
            tex_image.image = self.get_or_load_texture(tex_path)
            tex_image.location = (-400, 200)

            output = nodes.new("ShaderNodeOutputMaterial")
            output.location = (200, 0)
            links.new(tex_image.outputs["Color"], output.inputs["Surface"])

            return {"output": output, "tex_image": tex_image}

        principled = nodes.new("ShaderNodeBsdfPrincipled")
        output = nodes.new("ShaderNodeOutputMaterial")
        principled.location = (-200, 0)
        output.location = (200, 0)
        links.new(principled.outputs["BSDF"], output.inputs["Surface"])

        tex_image = None
        if tex_path:
            tex_image = nodes.new("ShaderNodeTexImage")
            tex_image.image = self.get_or_load_texture(tex_path)
            tex_image.location = (-600, 200)
            links.new(tex_image.outputs["Color"], principled.inputs["Base Color"])

            if emission_strength and sum(emission_strength) > 0:
                strength = sum(emission_strength[:3]) / 3.0

                mix_node = nodes.new("ShaderNodeMixRGB")
                mix_node.blend_type = 'MULTIPLY'
                mix_node.location = (-400, -200)
                mix_node.inputs[0].default_value = 1.0
                mix_node.inputs[1].default_value = (*emission_strength, 1.0)
                links.new(tex_image.outputs["Color"], mix_node.inputs[2])

                if alpha_map:
                    alpha_image = nodes.new("ShaderNodeTexImage")
                    alpha_image.image = alpha_map
                    alpha_image.location = (-600, -400)
                    alpha_image.interpolation = 'Closest'

                    alpha_mix = nodes.new("ShaderNodeMixRGB")
                    alpha_mix.blend_type = 'MULTIPLY'
                    alpha_mix.location = (-200, -400)
                    alpha_mix.inputs[0].default_value = 1.0
                    links.new(mix_node.outputs["Color"], alpha_mix.inputs[1])
                    links.new(alpha_image.outputs["Color"], alpha_mix.inputs[2])

                    emission_input = alpha_mix.outputs["Color"]
                else:
                    emission_input = mix_node.outputs["Color"]

                links.new(emission_input, principled.inputs["Emission Color"])
                principled.inputs["Emission Strength"].default_value = strength

        # 🆕 Environment map support
        if env_tex:
            env_path = f"{self.base_dir}/maps/{env_tex}"
            env_image = nodes.new("ShaderNodeTexImage")
            env_image.image = self.get_or_load_texture(env_path)
            env_image.projection = "SPHERE"
            env_image.location = (-300, -300)

            tex_coord = nodes.new("ShaderNodeTexCoord")
            mapping = nodes.new("ShaderNodeMapping")
            mapping.vector_type = 'TEXTURE'
            tex_coord.location = (-600, -300)
            mapping.location = (-450, -300)

            links.new(tex_coord.outputs["Reflection"], mapping.inputs["Vector"])
            links.new(mapping.outputs["Vector"], env_image.inputs["Vector"])

            mix_rgb = nodes.new("ShaderNodeMixRGB")
            mix_rgb.blend_type = 'ADD'
            mix_rgb.inputs["Fac"].default_value = metallic
            mix_rgb.location = (-150, 0)

            if tex_image:
                links.new(tex_image.outputs["Color"], mix_rgb.inputs["Color1"])
            else:
                mix_rgb.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)

            links.new(env_image.outputs["Color"], mix_rgb.inputs["Color2"])
            links.new(mix_rgb.outputs["Color"], principled.inputs["Base Color"])

        if template_type == "ALPHA_CLIP" and tex_image and color_key:
            tex_image.interpolation = 'Closest'
            vec = nodes.new("ShaderNodeVectorMath")
            vec.operation = 'DISTANCE'
            vec.location = (0, 200)
            vec.inputs[1].default_value = color_key[:3]
            links.new(tex_image.outputs["Color"], vec.inputs[0])

            thr = nodes.new("ShaderNodeMath")
            thr.operation = 'GREATER_THAN'
            thr.inputs[1].default_value = 0.4
            thr.location = (200, 200)
            links.new(vec.outputs["Value"], thr.inputs[0])

            links.new(thr.outputs["Value"], principled.inputs["Alpha"])

        elif template_type == "ALPHA_MASK" and alpha_map:
            tex_image.interpolation = 'Closest'
            alpha_image = nodes.new("ShaderNodeTexImage")
            alpha_image.image = alpha_map
            alpha_image.location = (0, 200)
            alpha_image.interpolation = 'Closest'
            links.new(alpha_image.outputs["Color"], principled.inputs["Alpha"])

        elif template_type == "ALPHA_BLEND" and alpha_path:
            alpha_node = nodes.new("ShaderNodeTexImage")
            alpha_node.image = self.get_or_load_texture(alpha_path)
            alpha_node.location = (-400, -200)
            links.new(alpha_node.outputs["Color"], principled.inputs["Alpha"])

        return {
            "principled": principled,
            "output": output,
            "tex_image": tex_image
        }



    def set_material_data(self, material, diffuse, alpha_tex, env_tex, emission, alpha, metallic, use_color_key):
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links

        tex_path = f"{self.base_dir}/maps/{diffuse}" if diffuse else None
        alpha_path = f"{self.base_dir}/maps/{alpha_tex}" if alpha_tex else None
        pre_alpha_map = diffuse and diffuse.lower() not in [tex.lower() for tex in ALPHA_FALLBACK]
        color_key = self.get_color_key(tex_path) if use_color_key and tex_path else None
        alpha_map = self.create_alpha_image(tex_path, 0) if color_key and pre_alpha_map else None

        template_type = "OPAQUE"
        if alpha_map:
            template_type = "ALPHA_MASK"
        elif color_key:
            template_type = "ALPHA_CLIP"
        if alpha_tex:
            template_type = "ALPHA_BLEND"
        if diffuse and "sky" in diffuse.lower():
            template_type = "SKY_ATMOSPHERE"
            material.use_backface_culling = True
            material.use_backface_culling_shadow = True
            #material.shadow_method = 'NONE'

        template = self.get_material_template(template_type, nodes, links,tex_path, alpha_path, color_key, alpha_map,emission, env_tex=env_tex, metallic=metallic)
        principled = template.get("principled")

        if principled:
            principled.inputs["Metallic"].default_value = metallic
            principled.inputs["Specular IOR Level"].default_value = 0.0
            principled.inputs["Roughness"].default_value = 0.0
            if alpha:
                principled.inputs["Alpha"].default_value = alpha

        if template_type == "ALPHA_CLIP" and color_key:
            material.blend_method = 'CLIP'
            material.alpha_threshold = 0.5

        elif template_type == "ALPHA_MASK" and alpha_map:
            material.blend_method = 'CLIP'
            material.alpha_threshold = 0.5

        elif template_type == "ALPHA_BLEND" and alpha_tex:
            material.blend_method = 'BLEND'

    def deserialize_material(self, f):
        flags = Util.read_int_32(f)

        use_diffuse_tex = bool(flags & MTL_DIFFUSETEX)
        use_color_key   = bool(flags & MTL_COLORKEY)
        has_env_map     = bool(flags & MTL_ENVMAP)
        has_alpha_tex   = bool(flags & MTL_ADDEFFECT and flags & MTL_ALPHATEX)
        is_animated     = bool(flags & MTL_ANIMTEXDIFF)

        ambient  = [Util.read_float_32(f) for _ in range(3)]
        diffuse  = [Util.read_float_32(f) for _ in range(3)]
        emission = [Util.read_float_32(f) for _ in range(3)]
        alpha    = Util.read_float_32(f)

        metallic = 0.0
        env_tex = ""
        if has_env_map:
            metallic = Util.read_float_32(f)
            env_tex = Util.read_string(f)

        diffuse_tex = Util.read_string(f).lower()
        mat_name = diffuse_tex if diffuse_tex else "material"

        # Check for reuse
        mat = bpy.data.materials.get(mat_name)
        if mat:
            if has_alpha_tex:
                Util.read_string(f)  # Consume alpha texture name
            if is_animated:
                f.read(18)  # Skip animation metadata
            return mat

        alpha_tex = ""
        if has_alpha_tex:
            alpha_tex = Util.read_string(f).lower()
        if is_animated:
            f.read(18)

        mat = bpy.data.materials.new(name=mat_name)
        self.set_material_data(
            mat, diffuse_tex, alpha_tex, env_tex, emission, alpha, metallic, use_color_key
        )
        return mat


    def setWireFrame(self,mesh,showName):
        mesh['Mafia.wireframe'] = True
        mesh.display_type = 'WIRE'
        if showName:
            mesh.show_name = True

    def build_armature(self):
        if not self.armature or not self.joints:
            return

        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode="EDIT")

        arm_data = self.armature.data
        bone_map = {self.base_bone_name: arm_data.edit_bones[self.base_bone_name]}

        for name, matrix, parent_id, bone_id in self.joints:
            bone = arm_data.edit_bones.new(name)
            bone_map[name] = bone

            mat = Matrix(matrix)
            loc = mat.to_translation()
            scale = mat.to_scale()

            # Set parent and head
            if parent_id == 1:
                bone.parent = bone_map[self.base_bone_name]
                bone.head = loc

                if self.armature_scale_factor:
                    if self.armature_scale_factor != scale:
                        raise NotImplementedError("Non-uniform armature scaling is not supported.")
                else:
                    self.armature_scale_factor = scale

            else:
                if scale != Vector((1.0, 1.0, 1.0)):
                    raise NotImplementedError("Non-uniform armature scaling is not supported.")

                parent_name = self.frames_map.get(parent_id)
                if isinstance(parent_name, str) and parent_name in bone_map:
                    parent_bone = bone_map[parent_name]
                    bone.parent = parent_bone
                    bone.head = loc + parent_bone.head
                    print_debug(f"Parented {name} (ID {bone_id}) to {parent_name} (frame {parent_id})")
                else:
                    bone.parent = bone_map[self.base_bone_name]
                    bone.head = loc
                    print_debug(f"Parented {name} (ID {bone_id}) to base bone (no parent at frame {parent_id})")

            # Set tail direction (Y-axis forward in .4DS, Z-up in Blender)
            forward = mat.to_3x3() @ Vector((0, 1, 0))
            bone.tail = bone.head + forward.normalized() * 0.15

            print_debug(f"Set bone {name} (ID {bone_id}): head={bone.head}, tail={bone.tail}, parent={bone.parent.name if bone.parent else 'None'}")

        if self.armature_scale_factor:
            self.armature.scale = self.armature_scale_factor

        bpy.ops.object.mode_set(mode="OBJECT")
        print_debug(f"Armature built with {len(arm_data.bones)} bones")


    def apply_skinning(self, mesh, vertex_groups, bone_to_parent):
        mod = mesh.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = self.armature
        print_debug(f"Added armature modifier to {mesh.name} with armature {self.armature.name}")

        total_vertices = len(mesh.data.vertices)
        vertex_counter = 0

        if not vertex_groups:
            print_debug(f"[SKIP] No vertex groups found for {mesh.name}")
            return

        lod_vertex_groups = vertex_groups[0]
        bone_names = [name for _, name in sorted(self.bone_nodes.items())]

        for bone_id, num_locked, weights in lod_vertex_groups:
            bone_name = bone_names[bone_id] if bone_id < len(bone_names) else f"unknown_bone_{bone_id}"
            if bone_id >= len(bone_names):
                print_debug(f"[WARN] Bone ID {bone_id} exceeds bone list size ({len(bone_names)})")

            vg = mesh.vertex_groups.get(bone_name) or mesh.vertex_groups.new(name=bone_name)
            if vg.name == bone_name:
                print_debug(f"Using vertex group for bone {bone_name} (ID {bone_id})")

            # Assign locked verts
            if num_locked > 0:
                locked_indices = list(range(vertex_counter, vertex_counter + num_locked))
                vg.add(locked_indices, 1.0, "ADD")
                print_debug(f"Assigned {len(locked_indices)} locked verts to {bone_name}")
                vertex_counter += num_locked

            # Assign weighted verts
            if weights:
                weighted_indices = list(range(vertex_counter, vertex_counter + len(weights)))
                valid = [(i, w) for i, w in zip(weighted_indices, weights) if i < total_vertices]

                # Group by weight value
                grouped = {}
                for idx, weight in valid:
                    grouped.setdefault(weight, []).append(idx)

                for weight, indices in grouped.items():
                    vg.add(indices, weight, "REPLACE")

                print_debug(f"Assigned {len(valid)} weighted verts to {bone_name}")
                vertex_counter += len(weights)

        # Assign any remaining verts to base bone
        remaining = list(range(vertex_counter, total_vertices))
        if remaining:
            base_vg = mesh.vertex_groups.get(self.base_bone_name) or mesh.vertex_groups.new(name=self.base_bone_name)
            base_vg.add(remaining, 1.0, "ADD")
            print_debug(f"Assigned {len(remaining)} remaining verts to {self.base_bone_name}")

        print_debug(f"[DONE] Skinning complete for {mesh.name} ({total_vertices} verts total)")



    def apply_average_face_area_normals(self, bm, mesh_data, angle_limit=60.0):
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.normal_update()

        sharp_radians = radians(angle_limit)
        for e in bm.edges:
            if not e.is_manifold or len(e.link_faces) != 2:
                e.smooth = True
                continue

            f1, f2 = e.link_faces

            if f1.normal.length == 0 or f2.normal.length == 0:
                print_debug(f"[WARN] Skipping edge with zero-length normal on face(s): {f1.index}, {f2.index}")
                e.smooth = True
                continue

            angle = f1.normal.angle(f2.normal)
            e.smooth = angle <= sharp_radians

        sharp_edges = {e for e in bm.edges if not e.smooth}

        loop_normals = []
        for face in bm.faces:
            area = face.calc_area()
            for loop in face.loops:
                v = loop.vert
                accum = Vector((0.0, 0.0, 0.0))
                total_area = 0.0

                for linked_face in v.link_faces:
                    if linked_face == face:
                        area_contrib = area
                        face_normal = face.normal
                    else:
                        shares_smooth_edge = False
                        for edge in linked_face.edges:
                            if edge in face.edges and edge.smooth:
                                shares_smooth_edge = True
                                break

                        if not shares_smooth_edge:
                            continue
                        area_contrib = linked_face.calc_area()
                        face_normal = linked_face.normal

                    accum += face_normal * area_contrib
                    total_area += area_contrib

                final_normal = accum.normalized() if total_area > 0 else Vector((0.0, 0.0, 1.0))
                loop_normals.append(final_normal)

        bm.to_mesh(mesh_data)
        bm.free()
        mesh_data.update()

        mesh_data.normals_split_custom_set(loop_normals)


    def deserialize_object(self, f, materials, mesh, mesh_data, remove_doubles=False):
        #instance_id = Util.read_int_16(f)

        print(f"[READ] deserialize_object() reading instance_id at {f.tell()}")
        
        pos = f.tell()
        bytes_preview = f.read(2)

        print(f"[READ DEBUG] Bytes at {pos}: {bytes_preview} -> {struct.unpack('<H', bytes_preview)[0]}")

        #if instance_id > 0:
            #return None, None

        vertices_per_lod = []
        num_lods = Util.read_uint_8(f)

        for lod_idx in range(num_lods):
            draw = lod_idx == 0 or self.drawLODS

            if lod_idx > 0 and draw:
                name = f"{mesh.name}_lod{lod_idx}"
                mesh_data = bpy.data.meshes.new(name)
                lod_obj = bpy.data.objects.new(name, mesh_data)
                lod_obj.parent = mesh  # properly parent to base mesh
                self.collection.objects.link(lod_obj)
                mesh = lod_obj

            clipping_range = Util.read_float_32(f)
            num_vertices = Util.read_int_16(f)
            vertices_per_lod.append(num_vertices)

            if not draw:
                f.seek((12 + 12 + 8) * num_vertices, 1)
                num_face_groups = Util.read_uint_8(f)
                for _ in range(num_face_groups):
                    num_faces = Util.read_int_16(f)
                    f.seek(num_faces * 6 + 2, 1)
                continue

            bm = bmesh.new()
            vertices = []
            uvs = []

            for _ in range(num_vertices):
                pos = Util.read_vector3(f, reorder=True)
                norm = Util.read_vector3(f, reorder=True)
                uv = Util.read_vector2(f)
                vert = bm.verts.new(pos)
                vert.normal = norm
                vertices.append(vert)
                uvs.append((uv.x, -uv.y))  # flip V

            bm.verts.ensure_lookup_table()
            num_face_groups = Util.read_uint_8(f)

            uv_layer = bm.loops.layers.uv.new("UVMap")
            face_uvs = []

            for _ in range(num_face_groups):
                num_faces = Util.read_int_16(f)
                slot_idx = len(mesh_data.materials)
                mesh_data.materials.append(None)

                for _ in range(num_faces):
                    idxs = Util.read_face_indices(f)
                    idxs_swap = (idxs[0], idxs[2], idxs[1])
                    try:
                        face = bm.faces.new([vertices[i] for i in idxs_swap])
                        face.material_index = slot_idx
                        face_uvs.append([uvs[i] for i in idxs_swap])
                    except ValueError:
                        print_debug(f"Warning: Duplicate face in '{mesh.name}' at {idxs_swap}")

                mat_idx = Util.read_int_16(f)
                if 0 < mat_idx <= len(materials):
                    mesh_data.materials[slot_idx] = materials[mat_idx - 1]

            for face, uvset in zip(bm.faces, face_uvs):
                for loop, uv in zip(face.loops, uvset):
                    loop[uv_layer].uv = uv

            if remove_doubles:
                try:
                    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
                except Exception as e:
                    print_debug(f"[WARN] remove_doubles failed on {mesh.name}: {e}")

            self.apply_average_face_area_normals(bm, mesh_data)

            for poly in mesh_data.polygons:
                poly.use_smooth = True

            if lod_idx > 0:
                mesh.hide_set(True)
                mesh.hide_render = True

            mesh.select_set(False)

        return num_lods, vertices_per_lod



    def deserialize_singlemesh(self, f, num_lods, mesh):
        armature_name = mesh.name

        # Initialize armature if it doesn't exist yet
        if not self.armature:
            arm_data = bpy.data.armatures.new(f"{armature_name}_bones")
            arm_data.display_type = "STICK"

            self.armature = bpy.data.objects.new(armature_name, arm_data)
            self.armature.show_in_front = True
            self.collection.objects.link(self.armature)

            print_debug(f"Created armature: {armature_name}")

            bpy.context.view_layer.objects.active = self.armature
            bpy.ops.object.mode_set(mode="EDIT")

            base_bone = self.armature.data.edit_bones.new(armature_name)
            base_bone.head = (0, -0.3, 0)
            base_bone.tail = (0, 0, 0)
            self.base_bone_name = base_bone.name

            print_debug(f"Created base bone: {base_bone.name}")

            bpy.ops.object.mode_set(mode="OBJECT")

        # Link mesh to armature
        mesh.name = armature_name
        self.armature.name = f"{armature_name}_armature"
        self.armature.parent = mesh
        print_debug(f"Set armature {self.armature.name} parent to mesh {mesh.name}")

        vertex_groups_per_lod = []
        bone_to_parent = {}

        for lod_id in range(num_lods):
            num_bones = Util.read_uint_8(f)
            _ = Util.read_int_32(f)  # numNonWeightedVerts
            _ = Util.read_vector3(f, reorder=True)  # minBounds
            _ = Util.read_vector3(f, reorder=True)  # maxBounds

            lod_vertex_groups = []

            for bone_id in range(num_bones):
                _ = struct.unpack("<16f", f.read(64))  # inverse transform matrix
                num_locked = Util.read_int_32(f)
                num_weighted = Util.read_int_32(f)
                file_bone_id = Util.read_int_32(f)
                _ = Util.read_vector3(f, reorder=True)  # boneMin
                _ = Util.read_vector3(f, reorder=True)  # boneMax
                weights = list(struct.unpack(f"<{num_weighted}f", f.read(4 * num_weighted)))

                # Resolve parent ID using file_bone_id
                parent_id = next((pid for _, _, pid, bid in self.joints if bid == file_bone_id), 0)
                bone_to_parent[bone_id] = parent_id
                lod_vertex_groups.append((bone_id, num_locked, weights))

                print_debug(f"Bone {bone_id} (File ID {file_bone_id}): {num_locked} locked, {num_weighted} weighted, parent ID {parent_id}")

            vertex_groups_per_lod.append(lod_vertex_groups)
            debug_lod_info = [(bid, nl, len(w)) for bid, nl, w in lod_vertex_groups]
            print_debug(f"LOD {lod_id} vertex_groups: {debug_lod_info}")

        self.skinned_meshes.append((mesh, vertex_groups_per_lod, bone_to_parent))
        print_debug(f"Stored in skinned_meshes: vertex_groups length = {len(vertex_groups_per_lod[0])}")
        return vertex_groups_per_lod



    def deserialize_target(self, f, empty, pos, rot, scale):
        unknown = Util.read_int_16(f)
        num_links = Util.read_uint_8(f)
        link_ids = struct.unpack(f"<{num_links}H", f.read(2 * num_links)) if num_links else []

        # Set display and transform
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        empty.show_name = True
        empty.location = pos
        empty.rotation_mode = "QUATERNION"
        empty.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        empty.scale = scale

        # Store links as custom property
        empty["link_ids"] = list(link_ids)

        print_debug(f"Set target {empty.name}: unknown={unknown}, links={list(link_ids)}, transform applied")



    def deserialize_morph(self, f, mesh, num_vertices_per_lod):
        num_targets = Util.read_uint_8(f)
        if num_targets == 0:
            print_debug("[MORPH] No targets — skipping morph block")
            return

        num_channels = Util.read_uint_8(f)
        num_lods = Util.read_uint_8(f)
        print_debug(f"[MORPH] Targets={num_targets}, Channels={num_channels}, LODs={num_lods}")

        if len(num_vertices_per_lod) != num_lods:
            print_debug(f"[WARN] LOD count mismatch: morph={num_lods}, object={len(num_vertices_per_lod)}")
            num_lods = min(num_lods, len(num_vertices_per_lod))

        morph_data = []
        for lod_idx in range(num_lods):
            lod_data = []
            for _ in range(num_channels):
                num_morph_vertices = Util.read_int_16(f)
                if num_morph_vertices == 0:
                    lod_data.append([])
                    continue

                vertex_data = []
                for _ in range(num_morph_vertices):
                    targets = []
                    for _ in range(num_targets):
                        p = Util.read_vector3(f, reorder=True)
                        n = Util.read_vector3(f, reorder=True)
                        targets.append((p, n))
                    vertex_data.append(targets)

                use_indices = struct.unpack("<?", f.read(1))[0]
                if use_indices:
                    vertex_indices = struct.unpack(f"<{num_morph_vertices}H", f.read(2 * num_morph_vertices))
                else:
                    vertex_indices = list(range(num_morph_vertices))

                lod_data.append((vertex_data, vertex_indices))
            morph_data.append(lod_data)

            f.read(12 * 3 + 4)  # Skip bounds block (min, max, center, distance)

        if not mesh.data.shape_keys:
            mesh.shape_key_add(name="Basis", from_mix=False)

        total_vertices = len(mesh.data.vertices)
        for lod_idx, lod_data in enumerate(morph_data):
            if total_vertices != num_vertices_per_lod[lod_idx]:
                print_debug(f"[SKIP] Vertex count mismatch: mesh={total_vertices}, LOD{lod_idx}={num_vertices_per_lod[lod_idx]}")
                continue

            for channel_idx, channel_data in enumerate(lod_data):
                if not channel_data:
                    continue

                vertex_data, vertex_indices = channel_data
                for target_idx in range(num_targets):
                    shape_key = mesh.shape_key_add(
                        name=f"Target_{target_idx}_LOD{lod_idx}_Channel{channel_idx}",
                        from_mix=False
                    )

                    updated_count = 0
                    for morph_idx, vert_idx in enumerate(vertex_indices):
                        if vert_idx < total_vertices:
                            target_pos, _ = vertex_data[morph_idx][target_idx]
                            shape_key.data[vert_idx].co = target_pos
                            updated_count += 1

                    print_debug(f"[MORPH] Created shape key '{shape_key.name}' — {updated_count} verts set")


    def deserialize_sector(self, f, mesh, pos, rot, scale):
        flags = Util.read_int_32(f), Util.read_int_32(f)
        num_vertices = Util.read_int_32(f)
        num_faces = Util.read_int_32(f)

        # Read AABB and vertices
        if self.version == 29:
            vertices = [Util.read_vector3(f, reorder=True) for _ in range(num_vertices)]
        elif self.version == 41:
            min_bounds = Util.read_quat(f, reorder=False)
            max_bounds = Util.read_quat(f, reorder=False)
            vertices = [Util.read_quat(f, reorder=False)[:3] for _ in range(num_vertices)]
        else:
            min_bounds = Util.read_vector3(f, reorder=True)
            max_bounds = Util.read_vector3(f, reorder=True)
            vertices = [Util.read_vector3(f, reorder=True) for _ in range(num_vertices)]

        faces = [Util.read_face_indices(f) for _ in range(num_faces)]

        if self.version == 29:
            min_bounds = Util.read_vector3(f, reorder=True)
            max_bounds = Util.read_vector3(f, reorder=True)

        # Read portals
        num_portals = Util.read_uint_8(f)
        portals = []
        for _ in range(num_portals):
            p_num_vertices = Util.read_uint_8(f)
            plane = Util.read_vector_4(f)
            p_flags = Util.read_int_32(f)
            near_range = Util.read_float_32(f)
            far_range = Util.read_float_32(f)
            if self.version != 29:
                _ = Util.read_int_32(f)
            p_vertices = [
                (Util.read_quat(f, reorder=False)[:3] if self.version == 41 else Util.read_vector3(f, reorder=True))
                for _ in range(p_num_vertices)
            ]
            portals.append((p_num_vertices, plane, p_flags, near_range, far_range, p_vertices))

        mesh_data = mesh.data
        mesh_data.from_pydata(vertices, [], faces)
        mesh_data.update()

        mesh.location = pos
        mesh.rotation_mode = "QUATERNION"
        mesh.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        mesh.scale = scale

        mesh["flags"] = [hex(f) for f in flags]
        mesh["min_bounds"] = min_bounds[:3] if self.version == 41 else min_bounds
        mesh["max_bounds"] = max_bounds[:3] if self.version == 41 else max_bounds
        mesh["num_portals"] = num_portals

        self.setWireFrame(mesh, True)
        print_debug(f"Created sector {mesh.name} with {num_vertices} vertices, {num_faces} faces")

        portal_meshes = []

        for i, (p_num_vertices, plane, p_flags, near_range, far_range, p_vertices) in enumerate(portals):
            portal_name = f"{mesh.name}_Portal{i}"
            portal_data = bpy.data.meshes.new(portal_name)
            portal_data.from_pydata(p_vertices, [], [])
            portal_mesh = bpy.data.objects.new(portal_name, portal_data)
            self.collection.objects.link(portal_mesh)

            portal_mesh.parent = mesh
            portal_mesh.matrix_parent_inverse = mesh.matrix_world.inverted()
            portal_mesh["plane"] = plane
            portal_mesh["flags"] = hex(p_flags)
            portal_mesh["near_range"] = near_range
            portal_mesh["far_range"] = far_range
            portal_mesh["isPortal"] = True
            portal_meshes.append(portal_mesh)

            self.setWireFrame(portal_mesh, True)
            print_debug(f"Created portal {portal_name} with {p_num_vertices} vertices")

        
        print_debug(f"Stored sector {mesh.name} custom props: flags {flags}, AABB {mesh['min_bounds']} to {mesh['max_bounds']}, {num_portals} portals")




    def deserialize_dummy(self, f, empty, pos, rot, scale):
        # Read and reorder bounding box to Z-up
        min_bounds = Util.read_vector3(f, reorder=True)
        max_bounds = Util.read_vector3(f, reorder=True)

        # Compute AABB size and display size
        aabb_size = max(
            max_bounds[i] - min_bounds[i]
            for i in range(3)
        ) * 0.5

        # Configure the empty object
        empty.empty_display_type = "CUBE"
        empty.empty_display_size = aabb_size
        empty.show_name = True
        empty.location = pos
        empty.rotation_mode = "QUATERNION"
        empty.rotation_quaternion = rot
        empty.scale = scale

        # Store bounding box as custom props
        empty["bbox_min"] = tuple(min_bounds)
        empty["bbox_max"] = tuple(max_bounds)



    def deserialize_occluder(self, f, mesh, pos, rot, scale):
        num_vertices = Util.read_int_32(f)
        num_faces = Util.read_int_32(f)

        if self.version == 41:  # HD2
            vertices = [Util.read_vector_4(f)[:3] for _ in range(num_vertices)]
            vertices = [(x, z, y) for x, y, z in vertices]
        else:  # Mafia or Chameleon
            vertices = [tuple(Util.read_vector3(f, reorder = True)) for _ in range(num_vertices)]

        faces = [Util.read_face_indices(f) for _ in range(num_faces)]

        mesh_data = mesh.data
        mesh_data.from_pydata(vertices, [], faces)
        mesh_data.update()

        print_debug(f"Created occluder mesh {mesh.name} with {num_vertices} vertices, {num_faces} faces")

        self.setWireFrame(mesh, True)
        print_debug(f"Set {mesh.name} display_type to WIRE, show_name True")

        # Apply transform
        mesh.location = pos
        mesh.rotation_mode = "QUATERNION"
        mesh.rotation_quaternion = rot
        mesh.scale = scale

        print_debug(f"Set {mesh.name} location to {pos}, rotation to {rot}, scale to {scale}")



    def is_material_blank(self, mat):
        if not mat or not mat.use_nodes:
            return True

        nodes = mat.node_tree.nodes
        output = nodes.get("Material Output")
        return (
            len(nodes) <= 1 or
            output is None or
            not output.inputs["Surface"].is_linked
        )

    def should_be_wireframe(self, obj):
        if obj.type != 'MESH':
            return False

        if not obj.material_slots:
            return True

        return all(self.is_material_blank(slot.material) for slot in obj.material_slots)


    def deserialize_frame(self, f, materials, frames):
        frame_type = Util.read_uint_8(f)
        visual_type, visual_flags = 0, (0, 0)

        if frame_type == FRAME_VISUAL:
            visual_type = Util.read_uint_8(f)
            visual_flags = f.read(2)

        parent_id = Util.read_int_16(f)
        position = Util.read_vector3(f, reorder=True)
        scale = Util.read_vector3(f, reorder=True)
        rot = Util.read_quat(f, reorder=True)

        rot_euler = rot.to_euler()
        transform_mat = (
            Matrix.Translation(position) @
            rot.to_matrix().to_4x4() @
            Matrix.Diagonal(scale).to_4x4()
        )

        culling_flags = Util.read_uint_8(f)
        name = Util.read_string(f)
        user_props = Util.read_string(f)

        print_debug(f"Creating frame #{self.frame_index} called {name} type {frame_type} visual {visual_type}")
        self.frame_types[self.frame_index] = frame_type

        if parent_id > 0:
            self.parenting_info.append((self.frame_index, parent_id))
            print_debug(f"Deferred parenting: frame {self.frame_index} to parent {parent_id}")

        mesh = None
        empty = None
        
        def make_mesh(name_suffix="", apply_local=True):
            mesh_data = bpy.data.meshes.new(name + name_suffix)
            mesh = bpy.data.objects.new(name, mesh_data)
            self.collection.objects.link(mesh)
            frames.append(mesh)
            self.frames_map[self.frame_index] = mesh
            if apply_local:
                mesh.matrix_local = transform_mat
            return mesh, mesh_data

        def make_dummy():
            empty = bpy.data.objects.new(name, None)
            self.collection.objects.link(empty)
            frames.append(empty)
            self.frames_map[self.frame_index] = empty
            return empty

        if frame_type == FRAME_VISUAL:
            if visual_type in (VISUAL_OBJECT, VISUAL_LITOBJECT):
                mesh, mesh_data = make_mesh("_mesh")
                self.frame_index += 1

                self.deserialize_object(f, materials, mesh, mesh_data, True)
                if self.should_be_wireframe(mesh):
                    self.setWireFrame(mesh, False)
                    print_debug(f"[WIRE] {mesh.name} set to wireframe due to blank material")

            elif visual_type == VISUAL_SINGLEMESH:
                mesh, mesh_data = make_mesh("_mesh")
                num_lods, _ = self.deserialize_object(f, materials, mesh, mesh_data)
                self.deserialize_singlemesh(f, num_lods, mesh)
                self.bones_map[self.frame_index] = self.base_bone_name
                self.frame_index += 1

            elif visual_type == VISUAL_BILLBOARD:
                mesh, mesh_data = make_mesh("_billboard")
                self.deserialize_object(f, materials, mesh, mesh_data)
                _ = Util.read_int_32(f)
                _ = Util.read_uint_8(f)
                self.frame_index += 1

            elif visual_type == VISUAL_SINGLEMORPH:
                mesh, mesh_data = make_mesh("_mesh")
                num_lods, verts_per_lod = self.deserialize_object(f, materials, mesh, mesh_data)
                self.deserialize_singlemesh(f, num_lods, mesh)
                self.deserialize_morph(f, mesh, verts_per_lod)
                self.bones_map[self.frame_index] = self.base_bone_name
                self.frame_index += 1

            elif visual_type == VISUAL_MORPH:
                mesh, mesh_data = make_mesh("_mesh")
                _, verts_per_lod = self.deserialize_object(f, materials, mesh, mesh_data)
                self.deserialize_morph(f, mesh, verts_per_lod)
                self.frame_index += 1

            else:
                print_debug(f"Unsupported visual type {visual_type} for '{name}'")
                return False

        elif frame_type in (FRAME_DUMMY, FRAME_TARGET):
            empty = make_dummy()
            if frame_type == FRAME_DUMMY:
                self.deserialize_dummy(f, empty, position, rot, scale)
            else:
                self.deserialize_target(f, empty, position, rot, scale)
            self.frame_index += 1

        elif frame_type in (FRAME_SECTOR, FRAME_OCCLUDER):
            mesh, mesh_data = make_mesh("", False)
            if frame_type == FRAME_SECTOR:
                self.deserialize_sector(f, mesh, position, rot, scale)
            else:
                self.deserialize_occluder(f, mesh, position, rot, scale)
            self.frame_index += 1

        elif frame_type == FRAME_JOINT:
            matrix = Util.read_matrix4x4(f)
            bone_id = Util.read_int_32(f)
            if self.armature:
                self.joints.append((name, transform_mat, parent_id, bone_id))
                self.bone_nodes[bone_id] = name
                self.bones_map[self.frame_index] = name
                self.frames_map[self.frame_index] = name
                print_debug(f"Collected joint: {name} (ID: {bone_id + 1}, Parent ID: {parent_id}, Pos: {position}, Rot: {rot_euler})")
                self.frame_index += 1

        else:
            print_debug(f"Unsupported frame type {frame_type} for '{name}'")
            return False

        if mesh is not None and len(user_props) > 0:
            mesh["Frame Properties"] = user_props
        if empty is not None and len (user_props) > 0:
            empty["Frame Properties"] = user_props

        return True

    def getCollection(self,collection,collection_name):
            
            if collection:
                return collection
            else:
                collection_name = collection_name or '4DS_Collection'
                if collection_name in bpy.data.collections:
                    collection = bpy.data.collections[collection_name]
                else:
                    collection = bpy.data.collections.new(collection_name)
                    bpy.context.scene.collection.children.link(collection)
                return collection


    def import_file(self, collection=None, collection_name=None):
        prefs = bpy.context.preferences.addons['Mafia_Formats'].preferences
        self.drawLODS = prefs.import_lods
        self.collection = self.getCollection(collection, collection_name)

        with open(self.filepath, "rb") as f:
            if Util.read_string_fixed(f, 4) != "4DS\0":
                print_debug("Error: Not a 4DS file")
                return

            self.version = Util.read_int_16(f)

            if self.version != VERSION_MAFIA:
                print_debug("Error: Only Mafia (version 29) 4DS files are supported")
                return

            f.read(8)  # Skip GUID

            materials = [self.deserialize_material(f) for _ in range(Util.read_int_16(f))]

            frame_count = Util.read_int_16(f)

            frames = []

            print(frame_count)
            for _ in range(frame_count):
                if not self.deserialize_frame(f, materials, frames):
                    break

            if self.armature and self.joints:
                self.build_armature()
                for mesh, vertex_groups, bone_to_parent in self.skinned_meshes:
                    self.apply_skinning(mesh, vertex_groups, bone_to_parent)

            self.apply_deferred_parenting()

            # Handle animation flag (not implemented yet)
            animation = Util.read_uint_8(f)

            if animation:
                print_debug("Note: Animation flag detected (not implemented)")

            return frames


    def apply_deferred_parenting(self):
        print_debug("Applying deferred parenting...")
        print_debug(f"Frames map: {self.frames_map}")
        print_debug(f"Bones map: {self.bones_map}")
        print_debug(f"Frame types: {self.frame_types}")
        print_debug(f"Parenting info: {self.parenting_info}")

        for frame_index, parent_id in self.parenting_info:
            if frame_index == parent_id:
                print_debug(f"Ignoring frame {frame_index} - parent set to itself")
                continue

            child_obj = self.frames_map.get(frame_index)
            if not child_obj or isinstance(child_obj, str):
                print_debug(f"Skipping parenting for frame {frame_index}: Invalid object {child_obj}")
                continue

            parent_entry = self.frames_map.get(parent_id)
            if parent_entry is None:
                print_debug(f"Warning: Parent {parent_id} not found for frame {frame_index}")
                continue

            parent_type = self.frame_types.get(parent_id, 0)

            if parent_type == FRAME_JOINT:
                if not self.armature:
                    print_debug(f"Warning: No armature to parent frame {frame_index} to joint {parent_id}")
                    continue

                bone_name = self.bones_map.get(parent_id)
                if not bone_name:
                    print_debug(f"Warning: Bone for joint {parent_id} not found in bones_map")
                    continue

                if bone_name not in self.armature.data.bones:
                    print_debug(f"Warning: Bone '{bone_name}' not found in armature")
                    continue

                self.parent_to_bone(child_obj, bone_name)
                print_debug(f"Parented frame {frame_index} ({child_obj.name}) to bone {bone_name}")
            else:
                if isinstance(parent_entry, str):
                    print_debug(f"Warning: Parent {parent_id} is a joint but frame type is {parent_type}")
                    continue

                child_obj.parent = parent_entry
                print_debug(f"Parented frame {frame_index} ({child_obj.name}) to frame {parent_id} ({parent_entry.name})")




class Import4DS(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.4ds"
    bl_label = "Import 4DS"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})

    def execute(self, context):
        importer = The4DSImporter(self.filepath)

        prefs = bpy.context.preferences.addons['Mafia_Formats'].preferences
        
        if prefs.maps_folder:
            importer.base_dir = bpy.path.abspath(prefs.maps_folder)

        parent_folder = os.path.basename(os.path.dirname(self.filepath))

        collection_name = None if parent_folder.lower() == "models" else parent_folder

        importer.import_file(None,collection_name)
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(Import4DS.bl_idname, text="4DS Model File (.4ds)")

def register():
    bpy.utils.register_class(Import4DS)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(Import4DS)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)