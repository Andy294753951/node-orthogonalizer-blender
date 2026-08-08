
######################################## LICENSE #################################################
# This program is free software: you can redistribute it and/or modify it under the terms of the #
# GNU General Public License as published by the Free Software Foundation, either version 3 of   #
# the License, or (at your option) any later version.                                            #
#                                                                                                #
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;      #
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.      #
# See the GNU General Public License for more details.                                           #
#                                                                                                #
# You should have received a copy of the GNU General Public License along with this program. If  #
# not, see <https://www.gnu.org/licenses/>.                                                      #
##################################################################################################

import platform
import time
import numpy as np
import bpy
from collections import namedtuple

OS = platform.system()
bl_info = {
    "name": "Node Orthogonalizer",
    "description": "Automatically routes Blender node links with clean right-angle turns",
    "author": "Kai Christensen",
    "version": (2, 0, 0),
    "blender": (3, 2, 0),
    "doc_url": "https://github.com/mkaic/square-noodles",
    "support": "COMMUNITY",
    "category": "Node",
}


Socket = namedtuple('Socket', ['socket', 'direction', 'x', 'y'])
Point = namedtuple('Point', ['x', 'y'])

# A reroute's RNA location is the top-left of its small drawing box, while
# links attach to the box centre. Treating location as the socket centre was
# the source of the small diagonal segments visible in Blender 5.x.
REROUTE_SIZE = 10.0

bpy.types.Node.is_reroute = bpy.props.BoolProperty(name="Is Reroute Node", default=False)
bpy.types.Node.x_lock = bpy.props.BoolProperty(name="X Lock", default=False)
bpy.types.Node.y_lock = bpy.props.BoolProperty(name="Y Lock", default=False)
bpy.types.NodeSocket.center_offset = bpy.props.FloatProperty(name="Center Offset", default=0)


def get_ui_scaling(context):
    """Return Blender's effective UI scale, including Windows display scale."""
    view_scale = context.preferences.view.ui_scale
    system_scale = context.preferences.system.ui_scale
    return max(float(view_scale) * float(system_scale), 0.01)


def get_undrawn_reroute_size(context):
    """Match the 0.5-pixel inset used by Blender's reroute drawing box."""
    ui_scaling = get_ui_scaling(context)
    return REROUTE_SIZE - (0.5 / ui_scaling)


def get_active_tree(context):
    tree = context.space_data.node_tree
    path = []
    # Get nodes from currently edited tree.
    # If user is editing a group, space_data.node_tree is still the base level (outside group).
    # context.active_node is in the group though, so if space_data.node_tree.nodes.active is not
    # the same as context.active_node, the user is in a group.
    # Check recursively until we find the real active node_tree:
    if tree.nodes.active:
        while tree.nodes.active != context.active_node:
            tree = tree.nodes.active.node_tree
            path.append(tree)
    return tree, path


def get_nodes_links(context):
    tree, path = get_active_tree(context)
    return tree.nodes, tree.links


def is_orphan(node):
    sockets = [*node.inputs, *node.outputs]
    linked_status = [x.is_linked for x in sockets]
    return not any(linked_status)

# code for calculating socket positions is taken from a SO post by Markus von Broady


def is_hidden(socket):
    return socket.hide or not socket.enabled


def is_tall(node, socket):
    if socket.type != 'VECTOR':
        return False
    if socket.hide_value:
        return False
    if socket.is_linked:
        return False
    if node.type == 'BSDF_PRINCIPLED' and socket.identifier == 'Subsurface Radius':
        return False  # an exception confirms a rule?
    return True


def assign_output_offsets(node, gap):

    outputs = [n for n in node.outputs if (not n.hide_value) and (n.is_linked)]
    n_out = len(outputs)

    if n_out > 1:
        spread = gap*(n_out-1)
        start = -1*spread/2
        stop = spread/2
        offsets = np.linspace(start=start, stop=stop, num=n_out)
        for offset, output in zip(offsets, outputs):
            output.center_offset = offset


def get_reroute_center(node, context):
    """Return the actual link socket centre of a reroute in node coordinates."""
    ui_scaling = get_ui_scaling(context)
    width = node.dimensions.x
    height = node.dimensions.y

    if OS == 'Darwin':
        width /= 2.0
        height /= 2.0

    fallback_size = get_undrawn_reroute_size(context)
    width = width / ui_scaling if width > 0 else fallback_size
    height = height / ui_scaling if height > 0 else fallback_size
    return Point(node.location.x + (width / 2.0),
                 node.location.y - (height / 2.0))


def set_reroute_center(node, x, y, context):
    """Place a reroute so its visible socket centre is exactly at (x, y)."""
    ui_scaling = get_ui_scaling(context)
    width = node.dimensions.x
    height = node.dimensions.y

    if OS == 'Darwin':
        width /= 2.0
        height /= 2.0

    fallback_size = get_undrawn_reroute_size(context)
    width = width / ui_scaling if width > 0 else fallback_size
    height = height / ui_scaling if height > 0 else fallback_size
    node.location = (x - (width / 2.0), y + (height / 2.0))


def align_reroute_center(node, context, x=None, y=None):
    """Move one or both reroute-centre axes without disturbing the other."""
    center = get_reroute_center(node, context)
    set_reroute_center(
        node,
        center.x if x is None else x,
        center.y if y is None else y,
        context,
    )


def get_socket_dict(node, context):
    inputs = list(reversed(node.inputs))
    outputs = node.outputs

    # Empty dict for holding input and output socket coordinates
    socket_dict = {'input': {}, 'output': {}}

    UI_SCALING = get_ui_scaling(context)

    Y_TOP = 38.25

    NORMAL_Y_BOTTOM = 10.25
    NORMAL_HEIGHT = 20.75

    VEC_Y_BOTTOM = 75
    VEC_HEIGHT = 82.5

    if OS == 'Darwin':
        # node.dimensions is mysteriously off by a factor of 2
        node_width = node.dimensions.x / 2
        node_height = node.dimensions.y / 2
    else:
        node_width = node.dimensions.x
        node_height = node.dimensions.y

    # Dimensions are the only reliable height for large node groups and image
    # nodes. They can be zero until the editor has drawn once, so retain RNA
    # width/height as a safe fallback for manual execution during that window.
    if node_width <= 0:
        node_width = node.width
    if node_height <= 0:
        node_height = node.height

    node_width = node_width/UI_SCALING
    node_height = node_height/UI_SCALING

    if (node.bl_idname != 'NodeReroute') and (not node.hide):

        # Walk up the inputs and store their positions (have to account for "tall" inputs)
        x = node.location.x
        y = node.location.y - node_height
        counter = 0
        for i in inputs:

            if is_hidden(i):
                continue

            tall = is_tall(node, i)

            if (counter == 0) and (tall):
                y += VEC_Y_BOTTOM
            if (counter == 0) and (not tall):
                y += NORMAL_Y_BOTTOM
            if (counter != 0) and (tall):
                y += VEC_HEIGHT
            if (counter != 0) and (not tall):
                y += NORMAL_HEIGHT

            socket_dict['input'][i.identifier] = Socket(i, 'input', x, y)
            counter += 1

        # Blender 5.x draws the first Principled BSDF inputs above a set of
        # collapsed panels. The RNA socket list still contains every panel
        # socket, so the legacy bottom-up walk places Base Color far too low.
        # These are the seven sockets that are visibly laid out above those
        # panels in Blender 5.2.
        if node.bl_idname == 'ShaderNodeBsdfPrincipled' and bpy.app.version >= (5, 0, 0):
            visible_principled_inputs = {
                'Base Color': 0,
                'Metallic': 1,
                'Roughness': 2,
                'IOR': 3,
                'Alpha': 4,
                'Thin Wall': 5,
                'Normal': 6,
            }
            for identifier, row in visible_principled_inputs.items():
                socket = node.inputs.get(identifier)
                if socket is not None and not is_hidden(socket):
                    socket_dict['input'][socket.identifier] = Socket(
                        socket,
                        'input',
                        node.location.x,
                        node.location.y - 59.0 - (row * 21.33),
                    )

        # These expanded vector controls have node-specific padding in 5.x.
        # Measuring from the top avoids accumulating the different control
        # heights that appear below them.
        if node.bl_idname == 'ShaderNodeMapping' and bpy.app.version >= (5, 0, 0):
            socket = node.inputs.get('Vector')
            if socket is not None and not is_hidden(socket):
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node.location.x,
                    node.location.y - 85.25,
                )

        if node.bl_idname == 'ShaderNodeTexNoise' and bpy.app.version >= (5, 0, 0):
            socket = node.inputs.get('Vector')
            if socket is not None and not is_hidden(socket):
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node.location.x,
                    node.location.y - 154.5,
                )

        # Material Output has a target selector above its inputs in Blender
        # 5.x, so its sockets are best measured from the node top.
        if node.bl_idname == 'ShaderNodeOutputMaterial' and bpy.app.version >= (5, 0, 0):
            for row, socket in enumerate(node.inputs):
                if not is_hidden(socket):
                    socket_dict['input'][socket.identifier] = Socket(
                        socket,
                        'input',
                        node.location.x,
                        node.location.y - 61.0 - (row * NORMAL_HEIGHT),
                    )

        # Group nodes draw outputs first, followed by the node-group selector,
        # then their inputs. Walking upward from the bottom accumulates errors
        # on large groups such as MMDShaderDev, so measure linked rows from the
        # top instead.
        if node.bl_idname == 'ShaderNodeGroup' and bpy.app.version >= (5, 0, 0):
            visible_outputs = [socket for socket in node.outputs if not is_hidden(socket)]
            visible_inputs = [socket for socket in node.inputs if not is_hidden(socket)]
            first_input_offset = Y_TOP + (len(visible_outputs) * NORMAL_HEIGHT) + 26.33
            for row, socket in enumerate(visible_inputs):
                row_offset = row * NORMAL_HEIGHT
                if node.node_tree and node.node_tree.name.startswith('MMDShaderDev'):
                    # mmd_tools deliberately switches to a slightly tighter
                    # layout after Sphere Tex Fac. These values were measured
                    # from Blender 5.2's rendered socket centres.
                    first_input_offset = 126.8236
                    row_offset = (
                        min(row, 8) * 21.33144
                        + max(row - 8, 0) * 20.67212
                    )
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node.location.x,
                    node.location.y - first_input_offset - row_offset,
                )

        # Blender 5.2 compositor nodes place their input sockets directly
        # below the header, even when large option panels make the node much
        # taller. The legacy bottom-up walk therefore fails badly for nodes
        # such as Blur and Glare.
        if node.bl_idname.startswith('CompositorNode') and bpy.app.version >= (5, 2, 0):
            visible_inputs = [socket for socket in node.inputs if not is_hidden(socket)]
            for row, socket in enumerate(visible_inputs):
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node.location.x,
                    node.location.y - Y_TOP - (row * NORMAL_HEIGHT),
                )

        # Walk down the outputs and store their positions
        x = node.location.x + node_width - 1.0
        y = node.location.y

        counter = 0
        for o in outputs:
            if is_hidden(o):
                continue

            if counter == 0:
                y -= Y_TOP
            if counter != 0:
                y -= NORMAL_HEIGHT

            socket_dict['output'][o.identifier] = Socket(o, 'output', x, y)
            counter += 1

        # Bake draws mode and action controls between its header and dynamic
        # item sockets. Each visible output shares a row with its matching
        # input, so reuse the already-correct bottom-up input coordinate. The
        # normal top-down output walk otherwise places every output above its
        # rendered socket in Blender 5.x.
        if node.bl_idname == 'GeometryNodeBake' and bpy.app.version >= (5, 0, 0):
            visible_inputs = [
                socket for socket in node.inputs
                if socket.identifier in socket_dict['input']
            ]
            visible_outputs = [
                socket for socket in node.outputs
                if socket.identifier in socket_dict['output']
            ]
            for input_socket, output_socket in zip(visible_inputs, visible_outputs):
                input_info = socket_dict['input'][input_socket.identifier]
                socket_dict['output'][output_socket.identifier] = Socket(
                    output_socket,
                    'output',
                    x,
                    input_info.y,
                )

    # For when the node is collapsed with sockets arranged in a semicircle at either end
    if (node.bl_idname != 'NodeReroute') and (node.hide):

        Y_CENTER_OFFSET = 10.0

        radius = node_height/2
        input_circle_center = Point(node.location.x + radius, node.location.y - Y_CENTER_OFFSET)
        output_circle_center = Point(node.location.x + node_width - radius, node.location.y - Y_CENTER_OFFSET)

        visible_inputs = [i for i in inputs if not is_hidden(i)]
        n_in = len(visible_inputs)
        slice_angle = np.pi/(n_in+1)
        for idx, i in enumerate(visible_inputs):

            slice = idx+1
            start = 3*np.pi/2
            x = input_circle_center.x + (np.cos(start-(slice*slice_angle))*radius)
            y = input_circle_center.y + (np.sin(start-(slice*slice_angle))*radius)

            socket_dict['input'][i.identifier] = Socket(i, 'input', x, y)

        visible_outputs = [o for o in outputs if not is_hidden(o)]
        n_out = len(visible_outputs)
        slice_angle = np.pi/(n_out+1)
        for idx, o in enumerate(visible_outputs):

            slice = idx+1
            start = np.pi/2
            x = output_circle_center.x + (np.cos(start-(slice*slice_angle))*radius)
            y = output_circle_center.y + (np.sin(start-(slice*slice_angle))*radius)

            socket_dict['output'][o.identifier] = Socket(o, 'output', x, y)

    if node.bl_idname == 'NodeReroute':
        x, y = get_reroute_center(node, context)
        for i in node.inputs:
            socket_dict['input'][i.identifier] = Socket(i, 'input', x, y)
        for o in node.outputs:
            socket_dict['output'][o.identifier] = Socket(o, 'output', x, y)

    return socket_dict


def check_aligned(socket_1, socket_2, tolerance):
    x1, y1 = (socket_1.x, socket_1.y)
    x2, y2 = (socket_2.x, socket_2.y)
    return (abs(x1 - x2) < tolerance) or (abs(y1 - y2) < tolerance)


class NODE_OT_orthogonalize(bpy.types.Operator):

    # Metadata class variables used by Blender to construct the operator's F3 menu button
    bl_idname = "node.orthogonalize"
    bl_label = "Node Orthogonalize"
    bl_description = \
        "Forces all non-locked noodles connect to selected nodes to be \
        straight lines with right-angle connections where necessary"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: bpy.props.FloatProperty(name="Tolerance",
                                       description="How off-axis a noodle must be before it is operated on.",
                                       default=5.0,
                                       min=1.0,
                                       max=25.0)
    nudge_limit: bpy.props.FloatProperty(name="Nudge Limit",
                                         description="Maximum distance existing reroute nodes will be nudged to try to align them before adding new reroute nodes.",
                                         default=100.0,
                                         min=0.0,
                                         max=200)
    noodle_margin: bpy.props.FloatProperty(name="Noodle Margin",
                                           description="Distance which overlapping noodles from different node outputs will hopefully be separated by.",
                                           default=20,
                                           min=0,
                                           max=100)
    auto_all: bpy.props.BoolProperty(
        name="Automatic All Nodes",
        description="Internal flag used by automatic mode to process all linked nodes",
        default=False,
        options={'HIDDEN'},
    )

    # The poll classmethod is called by Blender to determine whether the operator can be used in a given context. In our case,
    # we don't want it to be possible to use the operator outside of a Node Editor because we'd get an error if we tried that.
    @classmethod
    def poll(cls, context):
        space_data = context.space_data
        status = (space_data.type == 'NODE_EDITOR') and (space_data.node_tree is not None)
        return status

    # The function that's run when you click on the operator in the menu.
    def execute(self, context):

        # If snapping is on, turn it off. If it was on we'll turn it back on when we're done.
        snapping_on = context.tool_settings.use_snap_node
        if snapping_on:
            context.tool_settings.use_snap_node = False

        global_nodes, global_links = get_nodes_links(context)

        valid_nodes = [n for n in global_nodes if (self.auto_all or n.select)
                       and not is_orphan(n)]

        if len(valid_nodes) == 0:
            print('No nodes selected')
            return {'CANCELLED'}

        socket_dict = {}
        # Loops over all selected nodes
        for node in global_nodes:
            socket_dict[node.name] = get_socket_dict(node, context)
            node.is_reroute = node.bl_idname == 'NodeReroute'
            node.x_lock = not node.is_reroute
            node.y_lock = not node.is_reroute
            assign_output_offsets(node, self.noodle_margin)

        for root_node in valid_nodes:

            root_socket_dict = socket_dict[root_node.name]

            # for each linked socket, we'll loop through its links
            for root_direction in ['input', 'output']:
                linked_sockets = [s[1] for s in root_socket_dict[root_direction].items() if s[1].socket.is_linked]
                for root_socket_info in linked_sockets:
                    links = root_socket_info.socket.links
                    target_sockets = []
                    for link in links:

                       # Determining the target node and socket our root node and socket are connected to.
                        if root_direction == 'input':
                            target_node = link.from_node
                            target_socket = link.from_socket
                            target_direction = 'output'

                        if root_direction == 'output':
                            target_node = link.to_node
                            target_socket = link.to_socket
                            target_direction = 'input'

                        # Get a list of the sockets of the node we're connected to with this link,
                        # then filter for either inputs or outputs depending on the root socket direction
                        target_sockets.append((target_node.name, target_direction, target_socket.identifier))

                    # If we're a reroute node, try to ajust our position:
                    # 1. to be horizontally aligned with the nearest non-reroute socket we're connected to
                    # 2. to be aligned with the socket that requires the smallest non-breaking nudge to align with
                    if root_node.is_reroute:
                        non_reroute_targets, non_reroute_distances = [], []
                        reroute_targets, reroute_x_distances, reroute_y_distances = [], [], []
                        for path in target_sockets:
                            try:
                                target = socket_dict[path[0]][path[1]][path[2]]
                            except KeyError as e:
                                print('First Loop', e)
                                continue
                            target_node = target.socket.node
                            x_distance = (target.x - root_socket_info.x)
                            y_distance = (target.y - root_socket_info.y)
                            distance = x_distance**2 + y_distance**2
                            if not target_node.is_reroute:
                                non_reroute_targets.append(target)
                                non_reroute_distances.append(distance)
                            if target_node.is_reroute:
                                reroute_targets.append(target)
                                reroute_x_distances.append(x_distance)
                                reroute_y_distances.append(y_distance)

                        if (len(non_reroute_targets)) > 0 and (not root_node.y_lock):
                            closest_non_reroute_target = non_reroute_targets[np.argmin(non_reroute_distances)]
                            if abs(root_socket_info.y - closest_non_reroute_target.y) < self.nudge_limit:
                                align_reroute_center(
                                    root_node,
                                    context,
                                    y=closest_non_reroute_target.y,
                                )
                                root_node.y_lock = True

                            # Now that we've tried to align horizontally with the closest non-reroute socket,
                            # we will try to align with the closest reroute node we're connected to, then the
                            # next-closest if that doesn't work, then the next and the next etc. If we do align,
                            # on an axis, we lock that axis for both us and the node we align with.
                            if(len(reroute_targets)) > 0:
                                if (not root_node.x_lock) or (not root_node.y_lock):
                                    distances = list(np.square(reroute_x_distances) + np.square(reroute_y_distances))

                                    for attempt in range(len(reroute_targets)):
                                        closest_idx = np.argmin(distances)
                                        closest_reroute = reroute_targets.pop(closest_idx)
                                        x_distance = reroute_x_distances.pop(closest_idx)
                                        y_distance = reroute_y_distances.pop(closest_idx)
                                        closest_axis = np.argmin((x_distance, y_distance))
                                        if closest_axis == 0:
                                            if (abs(x_distance) < self.nudge_limit) and (not root_node.x_lock):
                                                align_reroute_center(
                                                    root_node,
                                                    context,
                                                    x=closest_reroute.x,
                                                )
                                                root_node.x_lock = True
                                                closest_reroute.socket.node.x_lock = True
                                            elif (abs(y_distance) < self.nudge_limit) and (not root_node.y_lock):
                                                align_reroute_center(
                                                    root_node,
                                                    context,
                                                    y=closest_reroute.y,
                                                )
                                                root_node.y_lock = True
                                                closest_reroute.socket.node.y_lock = True

                                        if closest_axis == 1:
                                            if (abs(y_distance) < self.nudge_limit) and (not root_node.y_lock):
                                                align_reroute_center(
                                                    root_node,
                                                    context,
                                                    y=closest_reroute.y,
                                                )
                                                root_node.y_lock = True
                                                closest_reroute.socket.node.y_lock = True
                                            elif (abs(x_distance) < self.nudge_limit) and (not root_node.x_lock):
                                                align_reroute_center(
                                                    root_node,
                                                    context,
                                                    x=closest_reroute.x,
                                                )
                                                root_node.x_lock = True
                                                closest_reroute.socket.node.x_lock = True

        # SECOND LOOP. IT DOES NEED TO BE TWO LOOPS.

        for root_node in valid_nodes:

            # We have to refresh our snapshot of the nodetree periodically because we're adding new nodes
            global_nodes, global_links = get_nodes_links(context)
            valid_nodes = [n for n in global_nodes if (self.auto_all or n.select)
                           and not is_orphan(n)]
            for check_node in global_nodes:
                socket_dict[check_node.name] = get_socket_dict(check_node, context)
                check_node.is_reroute = check_node.bl_idname == 'NodeReroute'

            root_socket_dict = socket_dict[root_node.name]

            # for each linked socket, we'll loop through its links
            for root_direction in ['input', 'output']:
                linked_sockets = [s[1] for s in root_socket_dict[root_direction].items() if s[1].socket.is_linked]
                for root_socket_info in linked_sockets:
                    links = root_socket_info.socket.links
                    target_sockets = []
                    for link in links:

                       # Determining the target node and socket our root node and socket are connected to.
                        if root_direction == 'input':
                            target_direction = 'output'
                            target_node = link.from_node
                            target_socket = link.from_socket

                        if root_direction == 'output':
                            target_direction = 'input'
                            target_node = link.to_node
                            target_socket = link.to_socket
                        try:
                            target_socket_info = socket_dict[target_node.name][target_direction][target_socket.identifier]
                        except KeyError as e:
                            print('Second Loop', e)
                            continue

                        # First, we check if these coordinates are already aligned (within a margin of error)
                        if check_aligned(root_socket_info, target_socket_info, self.tolerance):
                            # If they are, we can skip this link
                            continue
                        else:

                            root_x, root_y = root_socket_info.x, root_socket_info.y
                            target_x, target_y = target_socket_info.x, target_socket_info.y

                            global_links.remove(link)

                            root_socket = root_socket_info.socket

                            both_nodes = (not root_node.is_reroute) and (not target_node.is_reroute)
                            both_reroutes = (root_node.is_reroute) and (target_node.is_reroute)
                            hetero = (not both_nodes) and (not both_reroutes)

                            # If the nodes are both non-reroutes, create a "stairstep" pattern
                            # between them by deleting the existing link and adding two new reroute nodes and 3 new links
                            if both_nodes:
                                average_x_coord = (root_x + target_x) / 2

                            # Adding a calculated offset to the center x coords so multiple wires are less
                            # likely to overlap
                                if root_socket_info.direction == 'input':
                                    middle_x_coord = average_x_coord + target_socket.center_offset
                                if root_socket_info.direction == 'output':
                                    middle_x_coord = average_x_coord + root_socket.center_offset

                                reroute_1 = global_nodes.new('NodeReroute')
                                set_reroute_center(reroute_1, middle_x_coord, root_y, context)

                                reroute_2 = global_nodes.new('NodeReroute')
                                set_reroute_center(reroute_2, middle_x_coord, target_y, context)

                                if root_socket_info.direction == 'input':
                                    global_links.new(reroute_1.outputs[0], root_socket)
                                    global_links.new(target_socket, reroute_2.inputs[0])
                                    global_links.new(reroute_2.outputs[0], reroute_1.inputs[0])
                                if root_socket_info.direction == 'output':
                                    global_links.new(root_socket, reroute_1.inputs[0])
                                    global_links.new(reroute_2.outputs[0], target_socket)
                                    global_links.new(reroute_1.outputs[0], reroute_2.inputs[0])

                            # If one node is a reroute and the other isn't, though, we can add in just one reroute node
                            # and have it horizontally aligned with the normal node while vertically aligned with the
                            # reroute node.
                            if hetero:
                                if root_node.is_reroute:
                                    reroute = global_nodes.new('NodeReroute')
                                    set_reroute_center(reroute, root_x, target_y, context)
                                if target_node.is_reroute:
                                    reroute = global_nodes.new('NodeReroute')
                                    set_reroute_center(reroute, target_x, root_y, context)

                                if root_socket_info.direction == 'input':
                                    global_links.new(reroute.outputs[0], root_socket)
                                    global_links.new(target_socket, reroute.inputs[0])
                                if root_socket_info.direction == 'output':
                                    global_links.new(root_socket, reroute.inputs[0])
                                    global_links.new(reroute.outputs[0], target_socket)

                            # If both nodes are reroutes, we just travel sideways from the root node,
                            # place a reroute, then up/down to the target node
                            if both_reroutes:

                                reroute = global_nodes.new('NodeReroute')
                                set_reroute_center(reroute, target_x, root_y, context)

                                if root_socket_info.direction == 'input':
                                    global_links.new(reroute.outputs[0], root_socket)
                                    global_links.new(target_socket, reroute.inputs[0])
                                if root_socket_info.direction == 'output':
                                    global_links.new(root_socket, reroute.inputs[0])
                                    global_links.new(reroute.outputs[0], target_socket)

        # If the user had snapping on before, turn it back on.
        if snapping_on:
            context.tool_settings.use_snap_node = True

        return {'FINISHED'}


# store keymaps here to access after registration
addon_keymaps = []
_auto_timer_running = False
_auto_state = {}


class SquareNoodlesPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    auto_square: bpy.props.BoolProperty(
        name="Automatic Squaring",
        description="Automatically square selected noodles after nodes or links change",
        default=True,
    )
    auto_delay: bpy.props.FloatProperty(
        name="Automatic Delay",
        description="Seconds to wait after a change before squaring noodles",
        default=0.35,
        min=0.1,
        max=2.0,
    )
    auto_all_nodes: bpy.props.BoolProperty(
        name="Automatically Process All Nodes",
        description="Square every linked noodle in the active node tree instead of only selected nodes",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "auto_square")
        layout.prop(self, "auto_delay")
        layout.prop(self, "auto_all_nodes")


def _get_preferences():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def _tree_signature(tree):
    """Return a stable snapshot of node positions and links."""
    nodes = tuple(sorted(
        (
            node.name,
            node.bl_idname,
            round(float(node.location.x), 3),
            round(float(node.location.y), 3),
        )
        for node in tree.nodes
    ))
    links = tuple(sorted(
        (
            link.from_node.name,
            link.from_socket.identifier,
            link.to_node.name,
            link.to_socket.identifier,
        )
        for link in tree.links
    ))
    return nodes, links


def _tree_layout_ready(tree):
    """True once every linked non-reroute node has been drawn by the editor."""
    linked_nodes = {
        node
        for link in tree.links
        for node in (link.from_node, link.to_node)
        if node.bl_idname != 'NodeReroute'
    }
    return all(node.dimensions.x > 0 and node.dimensions.y > 0 for node in linked_nodes)


def _auto_square_timer():
    """Poll visible node editors and square after a change settles."""
    global _auto_state

    if not _auto_timer_running:
        return None

    preferences = _get_preferences()
    if preferences and not preferences.auto_square:
        _auto_state.clear()
        return 0.25

    delay = preferences.auto_delay if preferences else 0.35
    now = time.monotonic()
    seen_trees = set()

    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if not screen:
            continue

        for area in screen.areas:
            if area.type != 'NODE_EDITOR':
                continue

            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue

            try:
                with bpy.context.temp_override(
                    window=window,
                    screen=screen,
                    area=area,
                    region=region,
                ):
                    if bpy.context.space_data.node_tree is None:
                        continue

                    tree, _ = get_active_tree(bpy.context)
                    tree_key = tree.as_pointer()
                    if tree_key in seen_trees:
                        continue
                    seen_trees.add(tree_key)

                    if not _tree_layout_ready(tree):
                        area.tag_redraw()
                        _auto_state.pop(tree_key, None)
                        continue

                    signature = _tree_signature(tree)
                    state = _auto_state.get(tree_key)
                    if state is None:
                        _auto_state[tree_key] = {
                            'signature': signature,
                            'changed_at': now,
                        }
                        if tree.links:
                            bpy.ops.node.orthogonalize(
                                auto_all=preferences.auto_all_nodes if preferences else True
                            )
                            _auto_state[tree_key] = {
                                'signature': _tree_signature(tree),
                                'changed_at': now,
                            }
                        continue

                    if signature != state['signature']:
                        state['signature'] = signature
                        state['changed_at'] = now
                        continue

                    if now - state['changed_at'] < delay:
                        continue

                    bpy.ops.node.orthogonalize(
                        auto_all=preferences.auto_all_nodes if preferences else True
                    )
                    _auto_state[tree_key] = {
                        'signature': _tree_signature(tree),
                        'changed_at': now,
                    }
            except (AttributeError, ReferenceError, RuntimeError):
                # Areas and node trees can disappear while Blender changes screens.
                continue

    return 0.25


def register():
    global _auto_timer_running, _auto_state

    bpy.utils.register_class(SquareNoodlesPreferences)
    bpy.utils.register_class(NODE_OT_orthogonalize)

    # handle the keymap
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    # apparently the "name" field below is an enum with 190 options and they're not documented. Yeesh.
    if kc:
        km = kc.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
        kmi = km.keymap_items.new(
            NODE_OT_orthogonalize.bl_idname,
            'COMMA',
            'PRESS',
            ctrl=False,
            shift=True,
        )
        addon_keymaps.append((km, kmi))

    _auto_state = {}
    _auto_timer_running = True
    if not bpy.app.timers.is_registered(_auto_square_timer):
        bpy.app.timers.register(
            _auto_square_timer,
            first_interval=0.25,
            persistent=True,
        )


def unregister():
    global _auto_timer_running, _auto_state

    _auto_timer_running = False
    _auto_state.clear()
    if bpy.app.timers.is_registered(_auto_square_timer):
        bpy.app.timers.unregister(_auto_square_timer)


    # handle the keymap
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(NODE_OT_orthogonalize)
    bpy.utils.unregister_class(SquareNoodlesPreferences)


if __name__ == '__main__':
    register()
