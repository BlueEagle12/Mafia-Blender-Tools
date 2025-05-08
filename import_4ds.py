import os
import bpy
import bmesh
import struct
from mathutils import Quaternion, Matrix, Vector
from math import radians
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

class Import4DSPrefs(bpy.types.AddonPreferences): ## Optional
    bl_idname = __name__

    maps_folder: StringProperty(
        name="(Optional) Root Folder",
        subtype='DIR_PATH',
        default="",
        description="Parent dictonary of extracted maps (Typically your root mafia dictonary)"
    )

    def draw(self, context):
        self.layout.prop(self, "maps_folder")


bl_info = {
    "name": "LS3D 4DS Importer",
    "author": "Sev3n, Grok 3 (xAI)",
    "version": (1, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > 4DS Model File",
    "description": "Import LS3D .4ds files (currently only version 29 - Mafia)",
    "category": "Import-Export",
}

# FileVersion consts
VERSION_MAFIA = 29
VERSION_HD2 = 41
VERSION_CHAMELEON = 42

# FrameType consts
FRAME_VISUAL = 1
FRAME_LIGHT = 2
FRAME_CAMERA = 3
FRAME_SOUND = 4
FRAME_SECTOR = 5
FRAME_DUMMY = 6
FRAME_TARGET = 7
FRAME_USER = 8
FRAME_MODEL = 9
FRAME_JOINT = 10
FRAME_VOLUME = 11
FRAME_OCCLUDER = 12
FRAME_SCENE = 13
FRAME_AREA = 14
FRAME_LANDSCAPE = 15

# VisualType consts
VISUAL_OBJECT = 0
VISUAL_LITOBJECT = 1
VISUAL_SINGLEMESH = 2
VISUAL_SINGLEMORPH = 3
VISUAL_BILLBOARD = 4
VISUAL_MORPH = 5
VISUAL_LENS = 6
VISUAL_PROJECTOR = 7
VISUAL_MIRROR = 8
VISUAL_EMITOR = 9
VISUAL_SHADOW = 10
VISUAL_LANDPATCH = 11


class The4DSImporter:
    def __init__(self, filepath):
        self.filepath = filepath
        # Extract base directory dynamically
        dir_path = os.path.dirname(filepath)  # Parent directory
        parent_dir = os.path.basename(dir_path)  # e.g., "models" or "Intro"
        grandparent_path = os.path.dirname(dir_path)  # Grandparent directory
        grandparent_dir = os.path.basename(grandparent_path)  # e.g., "Mafia" or "missions"

        if (parent_dir.lower()) == "models":
            self.base_dir = grandparent_path  # Two levels up: E:/Mafia
        elif (grandparent_dir.lower()) == "missions":
            self.base_dir = os.path.dirname(
                grandparent_path
            )  # Three levels up: E:/Mafia
        else:
            # Fallback: assume two levels up (models-like structure)
            self.base_dir = os.path.dirname(os.path.dirname(filepath))

        # Normalize to ensure proper separators
        self.base_dir = os.path.normpath(self.base_dir)
        # NOTE: will be overridden by Add-on prefs if set
        print(f"Base directory set to: {self.base_dir}")
        self.version = 0
        self.materials = []
        self.skinned_meshes = []
        self.frames_map = {}
        self.frame_index = 1
        self.joints = []
        self.bone_nodes = {}  # Joint bone_id (0–16) to name
        self.base_bone_name = None  # Base bone name (e.g., "a")
        self.bones_map = {}
        self.armature = None
        self.armature_scale_factor = None
        self.parenting_info = []
        self.frame_types = {}
        # Texture cache
        self.texture_cache = {}  # Maps normalized filepath to bpy.data.images

    def parent_to_bone(self, obj, bone_name):
        # Ensure the context is correct for operator-based parenting
        bpy.ops.object.select_all(action="DESELECT")
        self.armature.select_set(True)
        bpy.context.view_layer.objects.active = self.armature

        # Set the active bone in edit mode
        bpy.ops.object.mode_set(mode="EDIT")
        if bone_name not in self.armature.data.edit_bones:
            print(f"Error: Bone {bone_name} not found in armature during parenting")
            bpy.ops.object.mode_set(mode="OBJECT")
            return
        edit_bone = self.armature.data.edit_bones[bone_name]
        self.armature.data.edit_bones.active = edit_bone

        bone_matrix = Matrix(edit_bone.matrix)

        # Switch back to object mode
        bpy.ops.object.mode_set(mode="OBJECT")

        # Select the child object and armature
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        self.armature.select_set(True)
        bpy.context.view_layer.objects.active = self.armature

        bone_matrix_tr = Matrix.Translation(
            bone_matrix.to_translation()
        )  # cut out the rotation part
        obj.matrix_basis = (
            self.armature.parent.matrix_world @ bone_matrix_tr @ obj.matrix_basis
        )

        # Perform the parenting operation
        bpy.ops.object.parent_set(type="BONE", xmirror=False, keep_transform=True)

        print(f"Successfully parented {obj.name} to bone {bone_name}")

    def read_string_fixed(self, f, length):
        data = f.read(length)
        try:
            return data.decode('cp1250', errors='ignore')
        except Exception:
            return data.decode('latin-1')

    def read_string(self, f):
        length = struct.unpack("B", f.read(1))[0]
        return self.read_string_fixed(f, length) if length > 0 else ""

    def get_color_key(self, filepath):
        """Extract the RGB color at palette index 0 from an indexed BMP."""
        try:
            with open(filepath, "rb") as f:
                f.seek(14)  # BMP header
                dib_size = struct.unpack("<I", f.read(4))[0]
                if dib_size == 40:  # BITMAPINFOHEADER
                    f.seek(36, 1)  # Offset to color table
                    b, g, r, _ = struct.unpack("<BBBB", f.read(4))  # BGRA
                    print(f"Color key: {r}, {g}, {b}")
                    return (r / 255.0, g / 255.0, b / 255.0)  # Normalized RGB
        except Exception as e:
            print(f"Warning: Could not read color key from {filepath}: {e}")
        return None

    def get_or_load_texture(self, filepath):
        # Normalize filepath for consistent lookup (lowercase, OS separators)
        norm_path = os.path.normpath(filepath.lower())
        if norm_path not in self.texture_cache:
            try:
                image = bpy.data.images.load(filepath, check_existing=True)
                self.texture_cache[norm_path] = image
                print(f"Loaded texture: {filepath}")
            except Exception as e:
                print(f"Warning: Failed to load texture {filepath}: {e}")
                self.texture_cache[norm_path] = (
                    None  # Cache None to avoid repeated attempts
                )
        else:
            print(f"Reused texture from cache: {filepath}")
        return self.texture_cache[norm_path]

    def set_material_data(
        self, material, diffuse, alpha_tex, emission, alpha, metallic, use_color_key
    ):
        # Prepare material for nodes
        material.use_nodes = True
        nt = material.node_tree
        nodes = nt.nodes
        links = nt.links
        nodes.clear()

        # Create core nodes
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        output    = nodes.new("ShaderNodeOutputMaterial")
        principled.location = (-200, 0)
        output.location    = ( 200, 0)

        # Configure principled inputs
        principled.inputs["Emission Color"].default_value = (*emission, 1.0)
        principled.inputs["Metallic"       ].default_value = metallic
        principled.inputs["Specular IOR Level"].default_value = 0.0
        principled.inputs["Roughness"      ].default_value = 0.0

        # Helper to wire principled → output if nothing else takes that slot
        def link_principled_to_output():
            links.new(principled.outputs["BSDF"], output.inputs["Surface"])

        # --- DIFFUSE TEXTURE + COLOR-KEY CUTOUT ---

        if diffuse:
            tex_path  = f"{self.base_dir}/maps/{diffuse}"
            tex_image = nodes.new("ShaderNodeTexImage")
            tex_image.image = self.get_or_load_texture(tex_path)
            tex_image.location = (-400, 200)
            links.new(tex_image.outputs["Color"], principled.inputs["Base Color"])

            if "sky" in diffuse.lower():
                material.use_backface_culling = True
                material.use_backface_culling_shadow = True
                links.new(tex_image.outputs["Color"], output.inputs["Surface"])

            tolerance = 0.47

            if use_color_key:
                color_key4 = self.get_color_key(tex_path)
                color_key = color_key4[:3]

                if diffuse == '^stromy1.bmp':
                    tolerance = 1

                if color_key:
                    vec = nodes.new("ShaderNodeVectorMath")
                    vec.operation = 'DISTANCE'
                    vec.location = (0, 200)
                    links.new(tex_image.outputs["Color"], vec.inputs[0])
                    vec.inputs[1].default_value = color_key # your key RGB

                    thr = nodes.new("ShaderNodeMath")
                    thr.operation = 'GREATER_THAN'
                    thr.inputs[1].default_value = tolerance       # e.g. 0.02
                    thr.location = (200, 200)
                    links.new(vec.outputs["Value"], thr.inputs[0])

                    # 2) Feed the mask directly into Principled Alpha
                    links.new(thr.outputs["Value"], principled.inputs["Alpha"])

                    # 3) Tell Blender to do a hard clip on your alpha
                    material.blend_method    = 'CLIP'
                    material.alpha_threshold = 0.5  # clips anything below 0.5 → transparent

                    # 4) Finally wire your Principled BSDF to the output
                    link_principled_to_output()
                else:
                    print(f"Warning: no color key for {diffuse}")
                    link_principled_to_output()
            else:
                link_principled_to_output()
        else:
            link_principled_to_output()

        # --- OPTIONAL ALPHA TEXTURE OVERRIDE ---
        if alpha_tex:
            alpha_path     = f"{self.base_dir}/maps/{alpha_tex}"
            alpha_tex_node = nodes.new("ShaderNodeTexImage")
            alpha_tex_node.image = self.get_or_load_texture(alpha_path)
            alpha_tex_node.location = (-400, -200)

            # Feed alpha into Principled and switch to BLEND mode
            links.new(alpha_tex_node.outputs["Color"], principled.inputs["Alpha"])
            material.blend_method = 'BLEND'

            # If you hadn’t already wired Principled→Output, do so now:
            # link_principled_to_output()


    def deserialize_material(self, f):
        flags = struct.unpack("<I", f.read(4))[0]

        use_diffuse_tex = (flags & 0x00040000) != 0
        use_color_key = (flags & 0x20000000) != 0
        ambient = struct.unpack("<3f", f.read(12))
        diffuse = struct.unpack("<3f", f.read(12))
        emission = struct.unpack("<3f", f.read(12))
        alpha = struct.unpack("<f", f.read(4))[0]

        metallic = 0.0
        if flags & 0x00080000:  # Env texture
            metallic = struct.unpack("<f", f.read(4))[0]
            self.read_string(f)  # Skip env texture name

        diffuse_tex = self.read_string(f).lower()
        mat_name = diffuse_tex if diffuse_tex else "material"

        # Reuse existing material if it exists
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)

            alpha_tex = ""
            if (flags & 0x00008000) and (flags & 0x40000000):  # Add effect + alpha texture
                alpha_tex = self.read_string(f).lower()

            if flags & 0x04000000:  # Animated diffuse
                struct.unpack("<I", f.read(4))  # Frames
                f.read(2)  # Skip
                struct.unpack("<I", f.read(4))  # Frame length
                f.read(8)  # Skip

            self.set_material_data(
                mat, diffuse_tex, alpha_tex, emission, alpha, metallic, use_color_key
            )
        return mat


    def build_armature(self):
        if not self.armature or not self.joints:
            return

        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode="EDIT")

        armature = self.armature.data
        bone_map = {self.base_bone_name: armature.edit_bones[self.base_bone_name]}

        # Process each joint
        for name, matrix, parent_id, bone_id in self.joints:
            bone = armature.edit_bones.new(name)
            bone_map[name] = bone

            # Convert matrix to location and scale (already Z-up)
            bone_matrix = Matrix(matrix)
            location = bone_matrix.to_translation()
            scale = bone_matrix.to_scale()

            # Set bone head and parent
            if parent_id == 1:  # Parent is the mesh (Node 0), root bone
                bone.parent = bone_map[self.base_bone_name]
                bone.head = location
                if self.armature_scale_factor:
                    if self.armature_scale_factor != scale:
                        raise NotImplementedError(
                            "Non-uniform armature scaling is not implemented."
                        )
                else:
                    self.armature_scale_factor = scale
            else:
                if scale != Vector((1.0, 1.0, 1.0)):
                    raise NotImplementedError(
                        "Non-uniform armature scaling is not implemented."
                    )
                parent_name = self.frames_map.get(parent_id)
                if isinstance(parent_name, str) and parent_name in bone_map:
                    bone.parent = bone_map[parent_name]
                    bone.head = Vector(location) + bone_map[parent_name].head
                    print(
                        f"Parented {name} (ID {bone_id}) to {parent_name} (frame {parent_id})"
                    )
                else:
                    bone.parent = bone_map[self.base_bone_name]
                    bone.head = location
                    print(
                        f"Parented {name} (ID {bone_id}) to {self.base_bone_name} (no parent at frame {parent_id})"
                    )

            # Set tail along matrix's forward direction (Y-axis in .4ds, Z-up in Blender)
            forward_dir = bone_matrix.to_3x3() @ Vector(
                (0, 1, 0)
            )  # .4ds Y-axis (forward)
            bone_length = 0.15  # Default length, tweakable
            bone.tail = bone.head + forward_dir.normalized() * bone_length

            print(
                f"Set bone {name} (ID {bone_id}): head {bone.head}, tail {bone.tail}, parent {bone.parent.name if bone.parent else 'None'}"
            )

        # Apply armature scale if set
        if self.armature_scale_factor:
            self.armature.scale = self.armature_scale_factor

        bpy.ops.object.mode_set(mode="OBJECT")
        print(f"Armature built with {len(armature.bones)} bones")

    def apply_skinning(self, mesh, vertex_groups, bone_to_parent):
        mod = mesh.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = self.armature
        print(
            f"Added armature modifier to {mesh.name} with armature {self.armature.name}"
        )

        total_vertices = len(mesh.data.vertices)
        vertex_counter = 0

        if vertex_groups:
            lod_vertex_groups = vertex_groups[0]
            bone_nodes = self.bone_nodes
            bone_names = sorted(
                bone_nodes.items(), key=lambda x: x[0]
            )  # Ensure order: [(0, "back1"), (1, "back2"), ...]
            bone_name_list = [
                name for _, name in bone_names
            ]  # ["back1", "back2", "back3", "l_shoulder", ...]

            for bone_id, num_locked, weights in lod_vertex_groups:
                if bone_id < len(bone_name_list):
                    bone_name = bone_name_list[bone_id]
                else:
                    print(
                        f"Warning: Bone ID {bone_id} exceeds available bone names ({len(bone_name_list)})"
                    )
                    bone_name = f"unknown_bone_{bone_id}"

                bvg = mesh.vertex_groups.get(bone_name)
                if not bvg:
                    bvg = mesh.vertex_groups.new(name=bone_name)
                    print(f"Created vertex group for bone {bone_name} (ID {bone_id})")
                else:
                    print(f"Reusing vertex group {bone_name} (ID {bone_id})")

                locked_vertices = list(
                    range(vertex_counter, vertex_counter + num_locked)
                )
                if locked_vertices:
                    bvg.add(locked_vertices, 1.0, "ADD")
                    for v_idx in locked_vertices:
                        print(
                            f"Assigned locked vertex {v_idx} to {bone_name} (ID {bone_id}) with weight 1.0"
                        )
                vertex_counter += num_locked

                weighted_vertices = list(
                    range(vertex_counter, vertex_counter + len(weights))
                )
                for i, w in zip(weighted_vertices, weights):
                    if i < total_vertices:
                        bvg.add([i], w, "REPLACE")
                        print(
                            f"Assigned weighted vertex {i} to {bone_name} (ID {bone_id}) with weight {w}"
                        )
                    else:
                        print(
                            f"Warning: Vertex index {i} out of range ({total_vertices})"
                        )
                vertex_counter += len(weights)

            base_vg = mesh.vertex_groups.get(self.base_bone_name)
            if not base_vg:
                base_vg = mesh.vertex_groups.new(name=self.base_bone_name)
                print(f"Created vertex group for base bone {self.base_bone_name}")
            base_vertices = list(range(vertex_counter, total_vertices))
            if base_vertices:
                base_vg.add(base_vertices, 1.0, "ADD")
                print(
                    f"Assigned {len(base_vertices)} non-weighted vertices ({vertex_counter}–{total_vertices-1}) to {self.base_bone_name}"
                )

        print(
            f"Completed skinning for {mesh.name}: {total_vertices} vertices processed"
        )

    def deserialize_object(self, f, materials, mesh, mesh_data):
        instance_id = struct.unpack("<H", f.read(2))[0]
        if instance_id > 0:
            return None, None

        vertices_per_lod = []

        num_lods = struct.unpack("<B", f.read(1))[0]
        for lod_idx in range(num_lods):
            if lod_idx > 0:
                name = f"{mesh.name}_lod{lod_idx}"
                mesh_data = bpy.data.meshes.new(name)
                new_mesh = bpy.data.objects.new(name, mesh_data)
                new_mesh.parent = mesh
                bpy.context.collection.objects.link(new_mesh)
                mesh = new_mesh

            clipping_range = struct.unpack("<f", f.read(4))[0]
            num_vertices = struct.unpack("<H", f.read(2))[0]

            vertices_per_lod.append(num_vertices)

            bm = bmesh.new()
            vertices = []
            uvs = []

            for _ in range(num_vertices):
                pos = struct.unpack("<3f", f.read(12))
                norm = struct.unpack("<3f", f.read(12))
                uv = struct.unpack("<2f", f.read(8))
                vert = bm.verts.new((pos[0], pos[2], pos[1]))
                vert.normal = (norm[0], norm[2], norm[1])
                vertices.append(vert)
                uvs.append((uv[0], -uv[1]))

            bm.verts.ensure_lookup_table()

            num_face_groups = struct.unpack("<B", f.read(1))[0]
            for group_idx in range(num_face_groups):
                num_faces = struct.unpack("<H", f.read(2))[0]
                mesh_data.materials.append(None)
                slot_idx = len(mesh_data.materials) - 1

                for _ in range(num_faces):
                    idxs = struct.unpack("<3H", f.read(6))
                    idxs_swap = (idxs[0], idxs[2], idxs[1])
                    try:
                        face = bm.faces.new([vertices[i] for i in idxs_swap])
                        face.material_index = slot_idx
                    except:
                        print(
                            f"Warning: Duplicate face in '{mesh.name}' at {idxs_swap}"
                        )

                mat_idx = struct.unpack("<H", f.read(2))[0]
                if mat_idx > 0 and mat_idx - 1 < len(materials):
                    mesh_data.materials[slot_idx] = materials[mat_idx - 1]

            bm.to_mesh(mesh_data)
            mesh_data.update()

            uv_layer = mesh_data.uv_layers.new()
            for face in mesh_data.polygons:
                for loop_idx, loop in enumerate(face.loop_indices):
                    vert_idx = mesh_data.loops[loop].vertex_index
                    uv_layer.data[loop].uv = uvs[vert_idx]

            bm.free()

            bpy.context.view_layer.objects.active = mesh
            mesh.select_set(True)
            bpy.ops.object.shade_smooth()
            if lod_idx > 0:
                mesh.hide_set(True)
                mesh.hide_render = True
            mesh.select_set(False)

        return num_lods, vertices_per_lod

    def deserialize_singlemesh(self, f, num_lods, mesh):
        armature_name = mesh.name
        if not self.armature:
            armature_data = bpy.data.armatures.new(armature_name + "_bones")
            armature_data.display_type = "STICK"
            self.armature = bpy.data.objects.new(armature_name, armature_data)
            self.armature.show_in_front = True
            bpy.context.collection.objects.link(self.armature)
            print(f"Created armature: {armature_name}")

            bpy.context.view_layer.objects.active = self.armature
            bpy.ops.object.mode_set(mode="EDIT")
            base_bone = self.armature.data.edit_bones.new(armature_name)
            base_bone.head = (0, -0.3, 0)
            base_bone.tail = (0, 0, 0)
            self.base_bone_name = base_bone.name
            print(f"Created base bone: {base_bone.name}")
            bpy.ops.object.mode_set(mode="OBJECT")

        mesh.name = armature_name
        self.armature.name = armature_name + "_armature"
        self.armature.parent = mesh
        print(f"Set armature {self.armature.name} parent to mesh {mesh.name}")

        vertex_groups = []  # List of (bone_id, num_locked, weights) tuples per LOD
        bone_to_parent = {}

        for lod_id in range(num_lods):
            num_bones = struct.unpack("<B", f.read(1))[0]
            num_non_weighted_verts = struct.unpack("<I", f.read(4))[0]
            min_bounds = struct.unpack("<3f", f.read(12))
            max_bounds = struct.unpack("<3f", f.read(12))

            lod_vertex_groups = []
            sequential_bone_id = 0  # Start at 0 and increment per bone

            for _ in range(num_bones):
                inverse_transform = struct.unpack("<16f", f.read(64))
                num_locked = struct.unpack("<I", f.read(4))[0]
                num_weighted = struct.unpack("<I", f.read(4))[0]
                file_bone_id = struct.unpack("<I", f.read(4))[
                    0
                ]  # Read but ignore for naming
                bone_min = struct.unpack("<3f", f.read(12))
                bone_max = struct.unpack("<3f", f.read(12))
                weights = list(
                    struct.unpack(f"<{num_weighted}f", f.read(4 * num_weighted))
                )

                # Use sequential ID instead of file_bone_id
                bone_id = sequential_bone_id
                sequential_bone_id += 1

                # Still use file_bone_id for parent lookup (if needed)
                parent_id = 0
                for _, _, pid, bid in self.joints:
                    if bid == file_bone_id:
                        parent_id = pid
                        break
                bone_to_parent[bone_id] = parent_id
                print(
                    f"Sequential Bone ID {bone_id} (File ID {file_bone_id}): {num_locked} locked, {num_weighted} weighted, parent ID {parent_id}"
                )

                lod_vertex_groups.append((bone_id, num_locked, weights))

            vertex_groups.append(lod_vertex_groups)
            print(
                f"LOD {lod_id} vertex_groups: {[(bid, nl, len(w)) for bid, nl, w in lod_vertex_groups]}"
            )

        self.skinned_meshes.append((mesh, vertex_groups, bone_to_parent))
        print(f"Stored in skinned_meshes: vertex_groups length={len(vertex_groups[0])}")
        return vertex_groups

    def deserialize_dummy(self, f, empty, pos, rot, scale):
        # Read bounding box
        min_bounds = struct.unpack("<3f", f.read(12))
        max_bounds = struct.unpack("<3f", f.read(12))

        # Convert to Blender Z-up (X, Y, Z) -> (X, Z, Y)
        min_bounds = (min_bounds[0], min_bounds[2], min_bounds[1])
        max_bounds = (max_bounds[0], max_bounds[2], max_bounds[1])

        aabb_size = (
            max_bounds[0] - min_bounds[0],
            max_bounds[1] - max_bounds[1],
            max_bounds[2] - min_bounds[2],
        )
        display_size = max(aabb_size[0], aabb_size[1], aabb_size[2]) * 0.5

        # Set empty display properties
        empty.empty_display_type = "CUBE"
        empty.empty_display_size = display_size
        empty.show_name = True  # Display name in viewport
        print(
            f"Set empty {empty.name} display type to CUBE, size 1.0, scale {empty.scale}, show_name True"
        )

        # Set transformation (unchanged)
        empty.location = pos
        empty.rotation_mode = "QUATERNION"
        empty.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        empty.scale = scale

        # Store bounding box as custom properties (unchanged)
        empty["bbox_min"] = min_bounds
        empty["bbox_max"] = max_bounds
        print(
            f"Set empty {empty.name} bbox_min to {empty['bbox_min']}, bbox_max to {empty['bbox_max']}"
        )

    def deserialize_target(self, f, empty, pos, rot, scale):
        # Read target data
        unknown = struct.unpack("<H", f.read(2))[0]  # uint16 unknown
        num_links = struct.unpack("<B", f.read(1))[0]  # ubyte numLinks
        link_ids = struct.unpack(
            f"<{num_links}H", f.read(2 * num_links)
        )  # uint16 linkIDs[numLinks]
        print(
            f"Target {empty.name}: unknown {unknown}, numLinks {num_links}, linkIDs {link_ids}"
        )

        # Set empty display properties
        empty.empty_display_type = "PLAIN_AXES"  # Visual cue for target
        empty.empty_display_size = 0.5  # Small size, tweakable
        empty.show_name = True  # Display name in viewport
        print(
            f"Set empty {empty.name} display type to PLAIN_AXES, size 0.5, show_name True"
        )

        # Set transformation
        empty.location = pos
        empty.rotation_mode = "QUATERNION"
        empty.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        empty.scale = scale
        print(
            f"Set empty {empty.name} location to {empty.location}, rotation to {empty.rotation_quaternion}, scale {empty.scale}"
        )

        # Store linkIDs as custom property
        empty["link_ids"] = list(link_ids)
        print(f"Set empty {empty.name} link_ids to {empty['link_ids']}")

    def deserialize_morph(self, f, mesh, num_vertices_per_lod):
        num_targets = struct.unpack("<B", f.read(1))[0]
        print(f"MORPH: num_targets={num_targets}")

        if num_targets == 0:
            return

        num_channels = struct.unpack("<B", f.read(1))[0]
        num_lods = struct.unpack("<B", f.read(1))[0]
        print(f"MORPH: num_channels={num_channels}, num_lods={num_lods}")

        # Validate num_lods matches the OBJECT structure
        if len(num_vertices_per_lod) != num_lods:
            print(
                f"Warning: MORPH num_lods ({num_lods}) does not match OBJECT num_lods ({len(num_vertices_per_lod)})"
            )
            num_lods = min(num_lods, len(num_vertices_per_lod))

        # Store morph data for each LOD and channel
        morph_data = []
        for lod_idx in range(num_lods):
            lod_data = []
            for channel_idx in range(num_channels):
                num_morph_vertices = struct.unpack("<H", f.read(2))[0]
                print(
                    f"MORPH LOD {lod_idx}, Channel {channel_idx}: num_morph_vertices={num_morph_vertices}"
                )

                if num_morph_vertices == 0:
                    lod_data.append([])
                    continue

                # Read morphed vertices
                vertex_data = []
                for vert_idx in range(num_morph_vertices):
                    targets = []
                    for target_idx in range(num_targets):
                        # Read position and normal (VECTOR3)
                        p = struct.unpack("<3f", f.read(12))
                        n = struct.unpack("<3f", f.read(12))
                        # Convert from 4DS Y-up to Blender Z-up: (X, Y, Z) -> (X, Z, Y)
                        p = (p[0], p[2], p[1])
                        n = (n[0], n[2], n[1])
                        targets.append((p, n))
                    vertex_data.append(targets)

                # Read unknown flag and vertex indices
                unknown = struct.unpack("<?", f.read(1))[0]
                vertex_indices = []
                if unknown:
                    vertex_indices = struct.unpack(
                        f"<{num_morph_vertices}H", f.read(2 * num_morph_vertices)
                    )
                    print(
                        f"MORPH LOD {lod_idx}, Channel {channel_idx}: vertex_indices={vertex_indices}"
                    )
                else:
                    # If unknown is False, assume indices are sequential
                    vertex_indices = list(range(num_morph_vertices))
                    print(
                        f"MORPH LOD {lod_idx}, Channel {channel_idx}: assuming sequential vertex_indices"
                    )

                lod_data.append((vertex_data, vertex_indices))
            morph_data.append(lod_data)

            min_bounds = struct.unpack("<3f", f.read(12))
            max_bounds = struct.unpack("<3f", f.read(12))
            center = struct.unpack("<3f", f.read(12))
            dist = struct.unpack("<f", f.read(4))
            # Convert to Blender Z-up
            min_bounds = (min_bounds[0], min_bounds[2], min_bounds[1])
            max_bounds = (max_bounds[0], max_bounds[2], max_bounds[1])
            center = (center[0], center[2], center[1])
        print(
            f"MORPH: min={min_bounds}, max={max_bounds}, center={center}, dist={dist}"
        )

        # Apply shape keys to the mesh for each LOD and channel
        if not mesh.data.shape_keys:
            mesh.shape_key_add(name="Basis", from_mix=False)

        for lod_idx in range(num_lods):
            num_vertices = num_vertices_per_lod[lod_idx]
            if len(mesh.data.vertices) != num_vertices:
                print(
                    f"Warning: Mesh vertex count ({len(mesh.data.vertices)}) does not match LOD {lod_idx} expected ({num_vertices})"
                )
                continue

            lod_data = morph_data[lod_idx]
            for channel_idx in range(num_channels):
                if not lod_data[channel_idx]:
                    continue

                vertex_data, vertex_indices = lod_data[channel_idx]
                for target_idx in range(num_targets):
                    shape_key_name = (
                        f"Target_{target_idx}_LOD{lod_idx}_Channel{channel_idx}"
                    )
                    shape_key = mesh.shape_key_add(name=shape_key_name, from_mix=False)
                    print(f"Created shape key: {shape_key_name}")

                    # Apply morph target positions
                    for morph_idx, vert_idx in enumerate(vertex_indices):
                        if vert_idx >= num_vertices:
                            print(
                                f"Warning: Vertex index {vert_idx} out of range for LOD {lod_idx} with {num_vertices} vertices"
                            )
                            continue
                        target_pos, _ = vertex_data[morph_idx][target_idx]
                        shape_key.data[vert_idx].co = target_pos
                        print(
                            f"Set shape key {shape_key_name} vertex {vert_idx} to position {target_pos}"
                        )

    def deserialize_sector(self, f, mesh, pos, rot, scale):
        # Read sector header
        flags = struct.unpack("<2I", f.read(8))  # uint32 flags[2]
        num_vertices = struct.unpack("<I", f.read(4))[0]  # uint32 numVertices
        num_faces = struct.unpack("<I", f.read(4))[0]  # uint32 numFaces

        # Read AABB and vertices based on version
        if self.version == 29:  # VERSION_MAFIA
            vertices = [
                struct.unpack("<3f", f.read(12)) for _ in range(num_vertices)
            ]  # VECTOR3
        elif self.version == 41:  # VERSION_HD2
            min_bounds = struct.unpack("<4f", f.read(16))  # VECTOR4 min
            max_bounds = struct.unpack("<4f", f.read(16))  # VECTOR4 max
            vertices = [
                struct.unpack("<4f", f.read(16)) for _ in range(num_vertices)
            ]  # VECTOR4
        else:  # VERSION_CHAMELEON (42)
            min_bounds = struct.unpack("<3f", f.read(12))  # VECTOR3 min
            max_bounds = struct.unpack("<3f", f.read(12))  # VECTOR3 max
            vertices = [
                struct.unpack("<3f", f.read(12)) for _ in range(num_vertices)
            ]  # VECTOR3

        # Read faces
        faces = [
            struct.unpack("<3H", f.read(6)) for _ in range(num_faces)
        ]  # FACE (3 uint16)

        # Read AABB for VERSION_MAFIA (after faces)
        if self.version == 29:
            min_bounds = struct.unpack("<3f", f.read(12))  # VECTOR3 min
            max_bounds = struct.unpack("<3f", f.read(12))  # VECTOR3 max

        # Read portals
        num_portals = struct.unpack("<B", f.read(1))[0]  # ubyte numPortals
        portals = []
        for i in range(num_portals):
            p_num_vertices = struct.unpack("<B", f.read(1))[0]  # ubyte numVertices
            plane = struct.unpack("<4f", f.read(16))  # PLANE (normal x, y, z, distance)
            p_flags = struct.unpack("<I", f.read(4))[0]  # uint32 flags
            near_range = struct.unpack("<f", f.read(4))[0]  # float nearRange
            far_range = struct.unpack("<f", f.read(4))[0]  # float farRange
            if self.version != 29:
                unknown = struct.unpack("<i", f.read(4))[0]  # int32 unknown
            p_vertices = (
                [struct.unpack("<4f", f.read(16)) for _ in range(p_num_vertices)]
                if self.version == 41
                else [struct.unpack("<3f", f.read(12)) for _ in range(p_num_vertices)]
            )  # VECTOR4 or VECTOR3
            portals.append(
                (p_num_vertices, plane, p_flags, near_range, far_range, p_vertices)
            )

        # Convert sector vertices to Blender Z-up (X, Z, Y) -> (X, Y, Z)
        if self.version == 41:
            vertices = [(v[0], v[2], v[1]) for v in vertices]  # VECTOR4 -> 3D, ignore w
        else:
            vertices = [(v[0], v[2], v[1]) for v in vertices]  # VECTOR3

        # Build sector mesh
        mesh_data = mesh.data
        mesh_data.from_pydata(vertices, [], faces)
        mesh_data.update()
        print(
            f"Created sector mesh {mesh.name} with {num_vertices} vertices, {num_faces} faces"
        )

        # Set sector as wireframe
        mesh.display_type = "WIRE"
        mesh.show_name = True
        print(f"Set {mesh.name} display_type to WIRE, show_name True")

        # Apply sector transform
        mesh.location = pos
        mesh.rotation_mode = "QUATERNION"
        mesh.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        mesh.scale = scale
        print(
            f"Set {mesh.name} location to {pos}, rotation to {mesh.rotation_quaternion}, scale to {scale}"
        )

        # Create portal meshes
        portal_meshes = []
        for i, (
            p_num_vertices,
            plane,
            p_flags,
            near_range,
            far_range,
            p_vertices,
        ) in enumerate(portals):
            # Convert portal vertices to Blender Z-up
            if self.version == 41:
                p_vertices = [(v[0], v[2], v[1]) for v in p_vertices]  # VECTOR4 -> 3D
            else:
                p_vertices = [(v[0], v[2], v[1]) for v in p_vertices]  # VECTOR3

            # Create portal mesh (no faces, just vertices as a wireframe outline)
            portal_name = f"{mesh.name}_Portal{i}"
            portal_data = bpy.data.meshes.new(portal_name)
            portal_data.from_pydata(
                p_vertices, [], []
            )  # No faces, wireframe will show edges
            portal_mesh = bpy.data.objects.new(portal_name, portal_data)
            bpy.context.collection.objects.link(portal_mesh)

            # Set as wireframe
            portal_mesh.display_type = "WIRE"
            portal_mesh.show_name = True
            print(
                f"Created portal mesh {portal_name} with {p_num_vertices} vertices, display_type WIRE"
            )

            # Parent to sector
            portal_mesh.parent = mesh
            portal_mesh.matrix_parent_inverse = mesh.matrix_world.inverted()
            print(f"Parented {portal_name} to {mesh.name}")

            # Store portal data as custom properties
            portal_mesh["plane"] = plane
            portal_mesh["flags"] = hex(p_flags)
            portal_mesh["near_range"] = near_range
            portal_mesh["far_range"] = far_range
            portal_meshes.append(portal_mesh)

        # Store sector custom properties
        mesh["flags"] = [hex(f) for f in flags]
        mesh["min_bounds"] = min_bounds[:3] if self.version == 41 else min_bounds
        mesh["max_bounds"] = max_bounds[:3] if self.version == 41 else max_bounds
        mesh["num_portals"] = num_portals
        print(
            f"Stored sector {mesh.name} custom props: flags {flags}, AABB {mesh['min_bounds']} to {mesh['max_bounds']}, {num_portals} portals"
        )

    def deserialize_occluder(self, f, mesh, pos, rot, scale):
        # Read occluder header
        num_vertices = struct.unpack("<I", f.read(4))[0]  # uint32 numVertices
        num_faces = struct.unpack("<I", f.read(4))[0]  # uint32 numFaces

        # Read vertices based on version
        if self.version == 41:  # VERSION_HD2
            vertices = [
                struct.unpack("<4f", f.read(16)) for _ in range(num_vertices)
            ]  # VECTOR4
        else:  # VERSION_MAFIA (29) or CHAMELEON (42)
            vertices = [
                struct.unpack("<3f", f.read(12)) for _ in range(num_vertices)
            ]  # VECTOR3

        # Read faces
        faces = [
            struct.unpack("<3H", f.read(6)) for _ in range(num_faces)
        ]  # FACE (3 uint16)

        # Convert vertices to Blender Z-up (X, Z, Y) -> (X, Y, Z)
        if self.version == 41:
            vertices = [(v[0], v[2], v[1]) for v in vertices]  # VECTOR4 -> 3D, ignore w
        else:
            vertices = [(v[0], v[2], v[1]) for v in vertices]  # VECTOR3

        # Build mesh
        mesh_data = mesh.data
        mesh_data.from_pydata(vertices, [], faces)
        mesh_data.update()
        print(
            f"Created occluder mesh {mesh.name} with {num_vertices} vertices, {num_faces} faces"
        )

        # Set as wireframe
        mesh.display_type = "WIRE"
        mesh.show_name = True  # Optional, like dummies
        print(f"Set {mesh.name} display_type to WIRE, show_name True")

        # Apply transform
        mesh.location = pos
        mesh.rotation_mode = "QUATERNION"
        mesh.rotation_quaternion = (rot[0], rot[1], rot[3], rot[2])
        mesh.scale = scale
        print(
            f"Set {mesh.name} location to {pos}, rotation to {mesh.rotation_quaternion}, scale to {scale}"
        )

    def deserialize_frame(self, f, materials, frames):
        frame_type = struct.unpack("<B", f.read(1))[0]
        visual_type = 0
        visual_flags = (0, 0)
        if frame_type == FRAME_VISUAL:
            visual_type = struct.unpack("<B", f.read(1))[0]
            visual_flags = struct.unpack("<2B", f.read(2))

        parent_id = struct.unpack("<H", f.read(2))[0]
        position = struct.unpack("<3f", f.read(12))
        scale = struct.unpack("<3f", f.read(12))
        rot = struct.unpack("<4f", f.read(16))  # WXYZ

        pos = (position[0], position[2], position[1])
        scl = (scale[0], scale[2], scale[1])
        rot_euler = Quaternion([rot[0], rot[1], rot[3], rot[2]]).to_euler()
        rot_tuple = (rot[0], rot[1], rot[3], rot[2])

        scale_mat = Matrix.Diagonal(scl).to_4x4()
        rot_mat = Quaternion(rot_tuple).to_matrix().to_4x4()
        trans_mat = Matrix.Translation(pos)

        transform_mat = trans_mat @ rot_mat @ scale_mat

        culling_flags = struct.unpack("<B", f.read(1))[0]
        name = self.read_string(f)
        user_props = self.read_string(f)

        print(f"Creating frame #{self.frame_index} called {name}")

        # Store frame type
        self.frame_types[self.frame_index] = frame_type

        if parent_id > 0:
            self.parenting_info.append((self.frame_index, parent_id))
            print(f"Deferred parenting: frame {self.frame_index} to parent {parent_id}")

        if frame_type == FRAME_VISUAL:
            if visual_type == VISUAL_OBJECT or visual_type == VISUAL_LITOBJECT:
                mesh_data = bpy.data.meshes.new(name + "_mesh")
                mesh = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(mesh)
                frames.append(mesh)
                self.frames_map[self.frame_index] = mesh

                self.frame_index += 1

                mesh.matrix_local = transform_mat
                # mesh.location = pos
                # mesh.scale = scl
                # mesh.rotation_euler = rot_euler

                self.deserialize_object(f, materials, mesh, mesh_data)

            elif visual_type == VISUAL_SINGLEMESH:
                mesh_data = bpy.data.meshes.new(name + "_mesh")
                mesh = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(mesh)
                frames.append(mesh)
                self.frames_map[self.frame_index] = mesh

                mesh.matrix_local = transform_mat
                # mesh.location = pos
                # mesh.scale = scl
                # mesh.rotation_euler = rot_euler

                num_lods, _ = self.deserialize_object(f, materials, mesh, mesh_data)
                self.deserialize_singlemesh(f, num_lods, mesh)

                self.bones_map[self.frame_index] = self.base_bone_name

                self.frame_index += 1

            elif visual_type == VISUAL_SINGLEMORPH:
                mesh_data = bpy.data.meshes.new(name + "_mesh")
                mesh = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(mesh)
                frames.append(mesh)
                self.frames_map[self.frame_index] = mesh

                mesh.matrix_local = transform_mat

                # Deserialize OBJECT to build the mesh
                num_lods, vertices_per_lod = self.deserialize_object(
                    f, materials, mesh, mesh_data
                )

                # Deserialize SINGLEMESH for skinning
                self.deserialize_singlemesh(f, num_lods, mesh)

                self.bones_map[self.frame_index] = self.base_bone_name

                self.frame_index += 1

                # Deserialize MORPH for shape keys
                self.deserialize_morph(f, mesh, vertices_per_lod)

            elif visual_type == VISUAL_MORPH:
                mesh_data = bpy.data.meshes.new(name + "_mesh")
                mesh = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(mesh)
                frames.append(mesh)
                self.frames_map[self.frame_index] = mesh

                self.frame_index += 1

                mesh.matrix_local = transform_mat

                # Deserialize OBJECT to build the mesh
                _, vertices_per_lod = self.deserialize_object(
                    f, materials, mesh, mesh_data
                )

                # Deserialize MORPH for shape keys
                self.deserialize_morph(f, mesh, vertices_per_lod)

            else:
                print(f"Unsupported visual type {visual_type} for '{name}'")
                return False

        elif frame_type == FRAME_DUMMY:
            empty = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(empty)
            frames.append(empty)
            self.frames_map[self.frame_index] = empty

            self.frame_index += 1

            # Pass transformation data directly
            self.deserialize_dummy(f, empty, pos, rot_tuple, scl)

        elif frame_type == FRAME_TARGET:
            empty = bpy.data.objects.new(name, None)
            bpy.context.collection.objects.link(empty)
            frames.append(empty)

            self.frames_map[self.frame_index] = empty

            self.frame_index += 1

            self.deserialize_target(f, empty, pos, rot_tuple, scl)

        elif frame_type == FRAME_SECTOR:
            mesh_data = bpy.data.meshes.new(name)  # Create mesh datablock
            mesh = bpy.data.objects.new(name, mesh_data)  # Create mesh object
            bpy.context.collection.objects.link(mesh)
            frames.append(mesh)

            self.frames_map[self.frame_index] = mesh

            self.frame_index += 1

            self.deserialize_sector(f, mesh, pos, rot_tuple, scl)

        elif frame_type == FRAME_OCCLUDER:
            mesh_data = bpy.data.meshes.new(name)  # Create mesh datablock
            mesh = bpy.data.objects.new(name, mesh_data)  # Create mesh object
            bpy.context.collection.objects.link(mesh)
            frames.append(mesh)

            self.frames_map[self.frame_index] = mesh

            self.frame_index += 1

            self.deserialize_occluder(f, mesh, pos, rot_tuple, scl)

        elif frame_type == FRAME_JOINT:
            matrix = struct.unpack("<16f", f.read(64))
            bone_id = struct.unpack("<I", f.read(4))[0]

            if self.armature:
                self.joints.append((name, transform_mat, parent_id, bone_id))

                self.bone_nodes[bone_id] = name
                self.bones_map[self.frame_index] = name
                self.frames_map[self.frame_index] = name

                print(
                    f"Collected joint: {name} (ID: {bone_id + 1}, Parent ID: {parent_id}, Pos: {pos}, Rot: {rot_euler})"
                )

                self.frame_index += 1

        else:
            print(f"Unsupported frame type {frame_type} for '{name}'")
            return False

        return True

    def import_file(self):
        with open(self.filepath, "rb") as f:
            if self.read_string_fixed(f, 4) != "4DS\0":
                print("Error: Not a 4DS file")
                return

            self.version = struct.unpack("<H", f.read(2))[0]
            if self.version != VERSION_MAFIA:
                print(
                    f"Error: This addon currently only supports 4DS version for Mafia (version 29)."
                )
                return

            f.read(8)  # Skip GUID

            mat_count = struct.unpack("<H", f.read(2))[0]
            materials = [self.deserialize_material(f) for _ in range(mat_count)]

            frame_count = struct.unpack("<H", f.read(2))[0]
            frames = []
            for _ in range(frame_count):
                if not self.deserialize_frame(f, materials, frames):
                    break

            if self.armature and self.joints:
                self.build_armature()  # Build once
                for mesh, vertex_groups, bone_to_parent in self.skinned_meshes:
                    self.apply_skinning(mesh, vertex_groups, bone_to_parent)

            # Post-process: Apply deferred parenting
            self.apply_deferred_parenting()

            is_animated = struct.unpack("<B", f.read(1))[0]
            if is_animated:
                print("Note: Animation flag detected (not implemented)")

    def apply_deferred_parenting(self):
        print("Applying deferred parenting...")
        print(f"Frames map: {self.frames_map}")
        print(f"Bones map: {self.bones_map}")
        print(f"Frame types: {self.frame_types}")
        print(f"Parenting info: {self.parenting_info}")

        for frame_index, parent_id in self.parenting_info:
            if frame_index not in self.frames_map:
                print(f"Warning: Frame {frame_index} not found in frames_map")
                continue

            if frame_index == parent_id:
                print(f"Ignoring frame {frame_index} - parent set to itself")
                continue

            parent_type = self.frame_types.get(parent_id, 0)

            child_obj = self.frames_map[frame_index]
            if child_obj is None or isinstance(
                child_obj, str
            ):  # Joints are stored as names
                print(
                    f"Skipping parenting for frame {frame_index}: Not a valid object (value: {child_obj})"
                )
                continue

            if parent_id not in self.frames_map:
                print(
                    f"Warning: Parent {parent_id} for frame {frame_index} not found in frames_map"
                )
                continue

            parent_entry = self.frames_map[parent_id]

            if parent_type == FRAME_JOINT:
                # Parent to the armature with the corresponding bone
                if not self.armature:
                    print(
                        f"Warning: No armature available to parent frame {frame_index} to joint {parent_id}"
                    )
                    continue

                parent_bone_name = self.bones_map.get(parent_id)
                if not parent_bone_name:
                    print(f"Warning: Bone for joint {parent_id} not found in bones_map")
                    continue

                if parent_bone_name not in self.armature.data.bones:
                    print(f"Warning: Bone {parent_bone_name} not found in armature")
                    continue

                # Set parent to armature with parent bone
                self.parent_to_bone(child_obj, parent_bone_name)
                print(
                    f"Parented frame {frame_index} ({child_obj.name}) to bone {parent_bone_name} in armature"
                )
            else:
                if isinstance(parent_entry, str):  # Parent is a joint
                    print(
                        f"Warning: Parent {parent_id} is a joint but frame type is {parent_type}"
                    )
                    continue
                # Regular object-to-object parenting
                parent_obj = parent_entry
                child_obj.parent = parent_obj
                print(
                    f"Parented frame {frame_index} ({child_obj.name}) to frame {parent_id} ({parent_obj.name})"
                )


class Import4DS(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.4ds"
    bl_label = "Import 4DS"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})

    def execute(self, context):
        # instantiate importer and then override base_dir if user set a custom maps folder
        importer = The4DSImporter(self.filepath)
        prefs = context.preferences.addons[__name__].preferences
        if prefs.maps_folder:
            importer.base_dir = bpy.path.abspath(prefs.maps_folder)
        importer.import_file()
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(Import4DS.bl_idname, text="4DS Model File (.4ds)")


def register():
    bpy.utils.register_class(Import4DSPrefs)
    bpy.utils.register_class(Import4DS)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(Import4DS)
    bpy.utils.unregister_class(Import4DSPrefs)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()
    register()