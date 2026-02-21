# ==============================
# Virtual Tabletop – Stable Base
# ==============================

import pygame
import tkinter as tk
from PIL import Image, ImageTk
import math
import os
from collections import deque
import json
SCENE_SAVE_FILE = "scenes.json"
current_scene="VAULT"
selected_char_index = 0
current_turn_char = None
segment_manager_mode = False
dragged_segment = None
seg_drag_offset = (0, 0)


# ------------------------------
# Tile and Map / MultiMap
# ------------------------------
class Tile:
    def __init__(self, walkable=False):
        self.walkable = walkable
        self.blocked_edges = {"N": False, "S": False, "E": False, "W": False}

class SingleMap:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.tiles = [[Tile() for _ in range(width)] for _ in range(height)]

    def get_tile(self, x, y):
        return self.tiles[y][x]

    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

class MapSegment:
    def __init__(self, filename, tilewidth, tileheight, offset_x=0, offset_y=0, name=None):
        self.filename = filename
        self.name = name or filename.split("\\")[-1]
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.map = loadfrompng(filename, tilewidth, tileheight)
        self.width = self.map.width
        self.height = self.map.height
        self.active = True

class MultiMap:
    def __init__(self):
        self.segments = []

    def add_segment(self, segment):
        self.segments.append(segment)

    @property
    def width(self):
        return max((seg.offset_x + seg.width for seg in self.segments if getattr(seg, "active", True)), default=0)

    @property
    def height(self):
        return max((seg.offset_y + seg.height for seg in self.segments if getattr(seg, "active", True)), default=0)

    def get_tile(self, x, y):
        for seg in self.segments:
            if not getattr(seg, "active", True):
                continue
            lx, ly = x - seg.offset_x, y - seg.offset_y
            if 0 <= lx < seg.width and 0 <= ly < seg.height:
                return seg.map.get_tile(lx, ly)
        return None

    def in_bounds(self, x, y):
        return self.get_tile(x, y) is not None


    def can_move(self, x1, y1, x2, y2):
        tile_from = self.get_tile(x1, y1)
        tile_to = self.get_tile(x2, y2)

        if not tile_to or not tile_from:
            return False

        if not tile_to.walkable:
            return False

        dx = x2 - x1
        dy = y2 - y1

        # Determine direction
        if dx == 1 and dy == 0:  # moving east
            if tile_from.blocked_edges["E"] or tile_to.blocked_edges["W"]:
                return False
        elif dx == -1 and dy == 0:  # moving west
            if tile_from.blocked_edges["W"] or tile_to.blocked_edges["E"]:
                return False
        elif dx == 0 and dy == 1:  # moving south
            if tile_from.blocked_edges["S"] or tile_to.blocked_edges["N"]:
                return False
        elif dx == 0 and dy == -1:  # moving north
            if tile_from.blocked_edges["N"] or tile_to.blocked_edges["S"]:
                return False

        return True


# ------------------------------
# Camera (works with SingleMap + MultiMap)
# ------------------------------
class Camera:
    def __init__(self, x, y, width, height, world):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.world = world   # this is the World object

        self.dragging = False
        self.drag_start = (0, 0)
        self.cam_start = (0, 0)

    def world_to_screen(self, wx, wy):
        return wx - self.x, wy - self.y

    def screen_to_world(self, sx, sy):
        return sx + self.x, sy + self.y

    def clamp(self):
        max_x = max(0, self.world.map.width - self.width)
        max_y = max(0, self.world.map.height - self.height)

        self.x = max(0, min(self.x, max_x))
        self.y = max(0, min(self.y, max_y))

    def center_on(self, wx, wy):
        self.x = int(wx - self.width // 2)
        self.y = int(wy - self.height // 2)
        self.clamp()




# ------------------------------
# Characters
# ------------------------------
class Character:
    def __init__(self, x, y, hp, str_score, dex, con, int_score, wis, cha, name):
        self.name = name
        self.x = x
        self.y = y
        self.hp = hp
        self.max_hp = hp
        self.abl = {"str": str_score, "dex": dex, "con": con,
                    "int": int_score, "wis": wis, "cha": cha}
        self.move_queue = []

    def update_position(self, world):
        if self.move_queue:
            dx, dy = self.move_queue.pop(0)
            nx, ny = self.x + dx, self.y + dy
            if world.map.can_move(self.x, self.y, nx, ny):
                self.x, self.y = nx, ny


class PlayerCharacter(Character):
    def __init__(self, *args):
        super().__init__(*args)
        self.initiative_roll = 0
        self.initiative_mod = (self.abl["dex"] - 10) // 2
        self.initiative = 0
        self.vision_radius=30
        self.vision_type=""

    def set_initiative(self, roll):
        self.initiative_roll = roll
        self.initiative = roll + self.initiative_mod

# ------------------------------
# Map loading from PNG
# ------------------------------
def loadfrompng(filename, tilewidth, tileheight):
    im = Image.open(filename).convert("RGB")
    width, height = im.size

    cols = width // tilewidth
    rows = height // tileheight

    game_map = SingleMap(cols, rows)
    pixels = im.load()

    for ty in range(rows):
        for tx in range(cols):
            tile = game_map.get_tile(tx, ty)

            # Sample center pixel → walkable
            cx = tx * tilewidth + tilewidth // 2
            cy = ty * tileheight + tileheight // 2
            r, g, b = pixels[cx, cy]

            tile.walkable = (r == 255 and g == 255 and b == 255)

            # ---- EDGE WALL DETECTION ----
            edges = {"N": False, "S": False, "E": False, "W": False}

            # North edge
            nx = cx
            ny = ty * tileheight
            if pixels[nx, ny] == (0, 0, 0):
                edges["N"] = True

            # South edge
            sx = cx
            sy = ty * tileheight + tileheight - 1
            if pixels[sx, sy] == (0, 0, 0):
                edges["S"] = True

            # West edge
            wx = tx * tilewidth
            wy = cy
            if pixels[wx, wy] == (0, 0, 0):
                edges["W"] = True

            # East edge
            ex = tx * tilewidth + tilewidth - 1
            ey = cy
            if pixels[ex, ey] == (0, 0, 0):
                edges["E"] = True

            tile.blocked_edges = edges

    return game_map

# ------------------------------
# World
# ------------------------------
class World:
    def __init__(self, game_map):
        self.map = game_map          # This is a MultiMap
        self.characters = []

    def add_characters(self, char):
        self.characters.append(char)

    def can_move_to(self, char, x, y):
        # Ask the MultiMap directly
        return self.map.can_move(char.x, char.y, x, y)


# ------------------------------
# Renderer
# ------------------------------
def update_fog_of_war(world, camera):
    fog_surface.fill((0, 0, 0, 255))  # full fog

    for c in world.characters:
        if not isinstance(c, PlayerCharacter):
            continue

        cx, cy = c.x + 0.5, c.y + 0.5  # player center
        radius = c.vision_radius
        points = []

        for angle in range(0, 360, 2):
            rad = math.radians(angle)
            dx, dy = math.cos(rad), math.sin(rad)

            x, y = cx, cy
            tx, ty = int(x), int(y)
            step_x = 1 if dx > 0 else -1
            step_y = 1 if dy > 0 else -1

            delta_x = abs(1 / dx) if dx != 0 else float("inf")
            delta_y = abs(1 / dy) if dy != 0 else float("inf")

            side_x = (tx + 1 - x) * delta_x if dx > 0 else (x - tx) * delta_x
            side_y = (ty + 1 - y) * delta_y if dy > 0 else (y - ty) * delta_y

            dist = 0
            hit = False

            while dist < radius and not hit:
                moving_diagonal = False

                if side_x < side_y:
                    # horizontal move
                    tx_next, ty_next = tx + step_x, ty
                    prev_tile = world.map.get_tile(tx, ty)
                    next_tile = world.map.get_tile(tx_next, ty_next)

                    # horizontal wall check
                    if (step_x == 1 and ((prev_tile and prev_tile.blocked_edges["E"]) or (next_tile and next_tile.blocked_edges["W"]))) \
                       or (step_x == -1 and ((prev_tile and prev_tile.blocked_edges["W"]) or (next_tile and next_tile.blocked_edges["E"]))):
                        hit = True
                        break

                    tx = tx_next
                    dist = side_x
                    side_x += delta_x
                else:
                    # vertical move
                    tx_next, ty_next = tx, ty + step_y
                    prev_tile = world.map.get_tile(tx, ty)
                    next_tile = world.map.get_tile(tx_next, ty_next)

                    # vertical wall check
                    if (step_y == 1 and ((prev_tile and prev_tile.blocked_edges["S"]) or (next_tile and next_tile.blocked_edges["N"]))) \
                       or (step_y == -1 and ((prev_tile and prev_tile.blocked_edges["N"]) or (next_tile and next_tile.blocked_edges["S"]))):
                        hit = True
                        break

                    ty = ty_next
                    dist = side_y
                    side_y += delta_y

                # --- CORNER COLLISION CHECK ---
                if step_x != 0 and step_y != 0:
                    tile_diag = world.map.get_tile(tx + step_x, ty + step_y)
                    tile_horiz = world.map.get_tile(tx + step_x, ty)
                    tile_vert = world.map.get_tile(tx, ty + step_y)

                    # check if moving through corner would cross walls on both axes
                    blocked_horiz = tile_horiz and ((step_x == 1 and tile_horiz.blocked_edges["W"]) or (step_x == -1 and tile_horiz.blocked_edges["E"]))
                    blocked_vert  = tile_vert and ((step_y == 1 and tile_vert.blocked_edges["N"]) or (step_y == -1 and tile_vert.blocked_edges["S"]))

                    if (blocked_horiz and blocked_vert) or (tile_diag and not tile_diag.walkable):
                        hit = True
                        break

                # stop at non-walkable tiles
                tile = world.map.get_tile(tx, ty)
                if tile and not tile.walkable and c.vision_type not in ("true_sight", "blindsight"):
                    hit = True
                    break

            # final pixel coordinates
            ray_dist = dist - 0.01
            px = int(cx * tile_size + dx * ray_dist * tile_size)
            py = int(cy * tile_size + dy * ray_dist * tile_size)
            points.append((px, py))

        if points:
            points.append(points[0])
            center_px = int(cx * tile_size)
            center_py = int(cy * tile_size)
            poly = [(center_px, center_py)] + points

            screen_poly = [(x - camera.x * tile_size, y - camera.y * tile_size) for x, y in poly]
            pygame.draw.polygon(fog_surface, (0, 0, 0, 0), screen_poly)
            pygame.draw.polygon(explored_surface, (0, 0, 0, 0), poly)




class Renderer:
    walkableclr = (255, 255, 255)
    blockedclr = (50, 50, 50)
    wallclr = (0, 0, 0)
    DMcolour = (200, 50, 50, 100)
    charclr = (0, 0, 255)

    def __init__(self, tilewidth, tileheight):
        self.tilewidth = tilewidth
        self.tileheight = tileheight

    def draw(self, screen, world, camera, dm_view=False):
        screen.fill((50, 50, 50))

        # Draw tiles
        for ty in range(camera.y, camera.y + camera.height):
            for tx in range(camera.x, camera.x + camera.width):
                if not world.map.in_bounds(tx, ty):
                    continue

                tile = world.map.get_tile(tx, ty)
                sx, sy = camera.world_to_screen(tx, ty)

                rect = pygame.Rect(
                    sx * self.tilewidth,
                    sy * self.tileheight,
                    self.tilewidth,
                    self.tileheight
                )

                colour = self.walkableclr if tile.walkable else self.blockedclr
                pygame.draw.rect(screen, colour, rect)

                # Grid
                pygame.draw.rect(screen, (100, 100, 100), rect, 1)
                # Draw interior walls (DM only or always – your choice)
                if tile.blocked_edges["N"]:
                    pygame.draw.line(screen, self.wallclr,
                                     rect.topleft, rect.topright, 3)

                if tile.blocked_edges["S"]:
                    pygame.draw.line(screen, self.wallclr,
                                     rect.bottomleft, rect.bottomright, 3)

                if tile.blocked_edges["W"]:
                    pygame.draw.line(screen, self.wallclr,
                                     rect.topleft, rect.bottomleft, 3)

                if tile.blocked_edges["E"]:
                    pygame.draw.line(screen, self.wallclr,
                                     rect.topright, rect.bottomright, 3)

                # DM overlay
                if dm_view and not tile.walkable:
                    overlay = pygame.Surface((self.tilewidth, self.tileheight), pygame.SRCALPHA)
                    overlay.fill(self.DMcolour)
                    screen.blit(overlay, rect.topleft)

        # Draw characters
        for char in world.characters:
            sx, sy = camera.world_to_screen(char.x, char.y)
            px = sx * self.tilewidth + self.tilewidth // 2
            py = sy * self.tileheight + self.tileheight // 2
            radius = self.tilewidth // 3

            pygame.draw.circle(screen, self.charclr, (px, py), radius)

            if world.characters.index(char) == selected_char_index:
                pygame.draw.circle(screen, (255, 255, 0), (px, py), radius + 2, 2)
        # ---- Fog of War (player view only) ----
        if not dm_view:
            screen.blit(
                explored_surface,
                (0, 0),
                area=pygame.Rect(
                    camera.x * tile_size,
                    camera.y * tile_size,
                    surface_width,
                    surface_height
                )
            )
            screen.blit(fog_surface, (0, 0))

        # ---- Segment manager overlay (DM only) ----
        if dm_view and segment_manager_mode:
            for seg in world.map.segments:
                # Segment world coords → screen
                sx, sy = camera.world_to_screen(seg.offset_x, seg.offset_y)

                rect = pygame.Rect(
                    sx * self.tilewidth,
                    sy * self.tileheight,
                    seg.width * self.tilewidth,
                    seg.height * self.tileheight
                )

                # Bounding box
                pygame.draw.rect(screen, (0, 200, 255), rect, 3)

                # Name label
                font = pygame.font.SysFont(None, 24)
                label = font.render(seg.name, True, (0, 200, 255))
                screen.blit(label, (rect.x + 4, rect.y + 4))


# ------------------------------
# Setup world and map segments
# ------------------------------
game_map = MultiMap()
def load_all_scenes():
    if not os.path.exists(SCENE_SAVE_FILE):
        return {}

    with open(SCENE_SAVE_FILE, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}

    # If old format (list), discard and reset
    if not isinstance(data, dict):
        print("WARNING: scenes.json was not a dict — resetting scene list")
        return {}

    return data


def save_all_scenes(data):
    with open(SCENE_SAVE_FILE, "w") as f:
        json.dump(data, f, indent=4)


def save_scene(scene_name, world):
    scenes = load_all_scenes()

    data = []
    for seg in world.map.segments:
        data.append({
            "filename": seg.filename,
            "offset_x": seg.offset_x,
            "offset_y": seg.offset_y,
            "active": seg.active
        })

    scenes[scene_name] = data
    save_all_scenes(scenes)

    print(f"Scene '{scene_name}' saved.")


def load_scene(scene_name, world):
    global current_scene

    scenes = load_all_scenes()
    if scene_name not in scenes:
        print("Scene not found:", scene_name)
        return

    layout = scenes[scene_name]

    for saved in layout:
        for seg in world.map.segments:
            if seg.filename == saved["filename"]:
                seg.offset_x = saved["offset_x"]
                seg.offset_y = saved["offset_y"]
                seg.active   = saved.get("active", True)

    current_scene = scene_name

    print(f"Scene '{scene_name}' loaded.")


segfolder=r"C:\Users\joshb\Documents\Virtual Tabletop\segments"
seg=[]
for i in range(len(os.listdir(segfolder))):
    seg.append(MapSegment(f"segments/room {i+1}.png", 70, 70, 0, 0, f"Segment {i+1}"))
    game_map.add_segment(seg[i])
world = World(game_map)
# Auto-load Default scene if exists
scenes = load_all_scenes()
if "VAULT" in scenes:
    load_scene("VAULT", world)

# Characters
edric = PlayerCharacter(43, 50, 100, 10, 14, 16, 25, 18, 14, "Edric Vale")
six   = PlayerCharacter(44, 50, 100, 10, 10, 10, 10, 10, 10, "Arthax Auditflame")
npc   = Character(50, 50, 100, 10, 10, 10, 10, 10, 10, "NPC")

world.add_characters(edric)
world.add_characters(six)
world.add_characters(npc)

current_turn_char = edric


# ------------------------------
# Tk + Pygame Setup
# ------------------------------
pygame.init()
root = tk.Tk()
root.withdraw()

screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()

# Tile size based on full MultiMap dimensions
BASE_TILE = 16   # base pixel size per tile at zoom = 1
tile_size = BASE_TILE


# How many tiles fit on screen
view_width  = 80
view_height = 80
surface_width  = view_width  * tile_size
surface_height = view_height * tile_size


player_surface = pygame.Surface((surface_width, surface_height))
dm_surface = pygame.Surface((surface_width, surface_height))
fog_surface = pygame.Surface((surface_width, surface_height), pygame.SRCALPHA)
WORLD_PX_WIDTH  = world.map.width  * tile_size
WORLD_PX_HEIGHT = world.map.height * tile_size

explored_surface = pygame.Surface((WORLD_PX_WIDTH, WORLD_PX_HEIGHT), pygame.SRCALPHA)
explored_surface.fill((0, 0, 0, 255))   # full unexplored







player_camera = Camera(0, 0, view_width, view_height, world)
dm_camera     = Camera(0, 0, view_width, view_height, world)



renderer = Renderer(tile_size, tile_size)

# Windows
player_win = tk.Toplevel()
player_win.title("Player View")
player_win.geometry(f"{surface_width}x{surface_height}+0+0")

dm_win = tk.Toplevel()
dm_win.title("DM View")
dm_win.geometry(f"{surface_width}x{surface_height}+0+0")

player_label = tk.Label(player_win)
player_label.pack(fill="both", expand=True)

dm_label = tk.Label(dm_win)
dm_label.pack(fill="both", expand=True)
player_label.configure(width=surface_width, height=surface_height)
dm_label.configure(width=surface_width, height=surface_height)
# ------------------------------
# Scene Manager Window (DM tool)
# ------------------------------
scene_win = tk.Toplevel()
scene_win.title("Scene Manager")
scene_win.geometry("300x200+50+50")

scene_var = tk.StringVar()
scene_var.set(current_scene)

scene_dropdown = tk.OptionMenu(scene_win, scene_var, "")
scene_dropdown.pack(fill="x", pady=5)

def refresh_scene_list():
    menu = scene_dropdown["menu"]
    menu.delete(0, "end")

    scenes = load_all_scenes()
    for name in scenes.keys():
        menu.add_command(label=name, command=lambda v=name: scene_var.set(v))

refresh_scene_list()
def load_selected_scene():
    name = scene_var.get()
    load_scene(name, world)


def save_current_scene():
    name = scene_var.get()
    save_scene(name, world)
    refresh_scene_list()


def create_new_scene():
    win = tk.Toplevel()
    win.title("New Scene")

    tk.Label(win, text="Scene name:").pack()
    entry = tk.Entry(win)
    entry.pack()

    def confirm():
        name = entry.get()
        if not name:
            return
        save_scene(name, world)
        scene_var.set(name)
        refresh_scene_list()
        win.destroy()

    tk.Button(win, text="Create", command=confirm).pack()


def delete_scene():
    name = scene_var.get()
    scenes = load_all_scenes()

    if name in scenes:
        del scenes[name]
        save_all_scenes(scenes)

    scene_var.set("Default")
    refresh_scene_list()
tk.Button(scene_win, text="Load Scene", command=load_selected_scene).pack(fill="x", pady=2)
tk.Button(scene_win, text="Save Scene", command=save_current_scene).pack(fill="x", pady=2)
tk.Button(scene_win, text="New Scene",  command=create_new_scene).pack(fill="x", pady=2)
tk.Button(scene_win, text="Delete Scene", command=delete_scene).pack(fill="x", pady=2)

def toggle_segment_manager(event=None):
    global segment_manager_mode
    segment_manager_mode = not segment_manager_mode
    print("Segment Manager:", "ON" if segment_manager_mode else "OFF")

dm_win.bind("<m>", toggle_segment_manager)
dm_win.bind("<M>", toggle_segment_manager)

def save_layout_hotkey(event=None):
    if segment_manager_mode:
        save_scene(current_scene, world)
        refresh_scene_list()


dm_win.bind("<s>", save_layout_hotkey)
dm_win.bind("<S>", save_layout_hotkey)




# ------------------------------
# Fog-of-War (persistent)
# ------------------------------
def update_fog_of_war(world, camera):
    # Reset only CURRENT fog (not explored memory)

    for c in world.characters:
        if not isinstance(c, PlayerCharacter):
            continue

        radius_tiles = c.vision_radius

        # Player position in screen pixels
        cx = int(c.x * tile_size + tile_size // 2)
        cy = int(c.y * tile_size + tile_size // 2)

        radius_px = radius_tiles * tile_size
        points = []

        # Ray fan
        for angle in range(0, 363, 3):
            rad = math.radians(angle)
            dx = math.cos(rad)
            dy = math.sin(rad)

            x, y = cx, cy
            last_x, last_y = cx, cy
            prev_tx, prev_ty = None, None

            for step in range(radius_px):
                px = int(x)
                py = int(y)

                # Outside WORLD
                if px < 0 or py < 0 or px >= WORLD_PX_WIDTH or py >= WORLD_PX_HEIGHT:
                    break

                # Pixel → world tile
                tx = int(px / tile_size)
                ty = int(py / tile_size)

                tile = world.map.get_tile(tx, ty)
                if tile is None:
                    break

                if prev_tx is not None:
                    dx_tile = tx - prev_tx
                    dy_tile = ty - prev_ty
                    prev_tile = world.map.get_tile(prev_tx, prev_ty)

                    def blocks(edge):
                        return edge is True

                    # Horizontal / vertical edge check
                    if dx_tile == 1 and (blocks(tile.blocked_edges["W"]) or blocks(prev_tile.blocked_edges["E"])):
                        break
                    if dx_tile == -1 and (blocks(tile.blocked_edges["E"]) or blocks(prev_tile.blocked_edges["W"])):
                        break
                    if dy_tile == 1 and (blocks(tile.blocked_edges["N"]) or blocks(prev_tile.blocked_edges["S"])):
                        break
                    if dy_tile == -1 and (blocks(tile.blocked_edges["S"]) or blocks(prev_tile.blocked_edges["N"])):
                        break

                    # Corner blocking: if moving diagonally, stop if either adjacent orthogonal tile blocks the corner
                    if dx_tile != 0 and dy_tile != 0:
                        neighbor_x = world.map.get_tile(prev_tx + dx_tile, prev_ty)
                        neighbor_y = world.map.get_tile(prev_tx, prev_ty + dy_tile)
                        if (neighbor_x and not neighbor_x.walkable) or (neighbor_y and not neighbor_y.walkable):
                            break

                last_x, last_y = px, py

                # Stop at solid tiles (unless special vision)
                if not tile.walkable and c.vision_type not in ("true_sight", "blindsight"):
                    break

                # Blindsight radius limit
                if c.vision_type == "blindsight" and step > radius_px:
                    break

                prev_tx, prev_ty = tx, ty
                x += dx
                y += dy

            points.append((last_x, last_y))

        # Cut visibility polygons
        if len(points) >= 3:
            poly = [(cx, cy)] + points

            # Convert world polygon → screen polygon
            screen_poly = [(int(wx - camera.x * tile_size), int(wy - camera.y * tile_size)) for wx, wy in poly]
            pygame.draw.polygon(fog_surface, (0, 0, 0, 0), screen_poly)
            pygame.draw.polygon(explored_surface, (0, 0, 0, 0), poly)



# ------------------------------
# Snap to nearest walkable
# ------------------------------
def snap_to_walkable(char, world):
    # If already valid, do nothing
    tile = world.map.get_tile(char.x, char.y)
    if tile and tile.walkable:
        return

    visited = set()
    queue = deque()

    queue.append((char.x, char.y))
    visited.add((char.x, char.y))

    while queue:
        x, y = queue.popleft()

        tile = world.map.get_tile(x, y)
        if tile and tile.walkable:
            char.x, char.y = x, y
            return

        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            nx, ny = x + dx, y + dy
            if (nx, ny) not in visited:
                visited.add((nx, ny))
                queue.append((nx, ny))


SNAP_DISTANCE = 1  # tiles

def snap_segment_to_others(seg, all_segments):
    """Move seg so it snaps to the nearest segment edge if close enough"""
    for other in all_segments:
        if other == seg or not getattr(other, "active", True):
            continue

        # Check all 4 edges: N, S, W, E
        # Snap N to S
        if abs(seg.offset_y - (other.offset_y + other.height)) <= SNAP_DISTANCE:
            if abs(seg.offset_x - other.offset_x) <= SNAP_DISTANCE or \
               abs(seg.offset_x + seg.width - (other.offset_x + other.width)) <= SNAP_DISTANCE:
                seg.offset_y = other.offset_y + other.height

        # Snap S to N
        if abs((seg.offset_y + seg.height) - other.offset_y) <= SNAP_DISTANCE:
            if abs(seg.offset_x - other.offset_x) <= SNAP_DISTANCE or \
               abs(seg.offset_x + seg.width - (other.offset_x + other.width)) <= SNAP_DISTANCE:
                seg.offset_y = other.offset_y - seg.height

        # Snap W to E
        if abs(seg.offset_x - (other.offset_x + other.width)) <= SNAP_DISTANCE:
            if abs(seg.offset_y - other.offset_y) <= SNAP_DISTANCE or \
               abs(seg.offset_y + seg.height - (other.offset_y + other.height)) <= SNAP_DISTANCE:
                seg.offset_x = other.offset_x + other.width

        # Snap E to W
        if abs((seg.offset_x + seg.width) - other.offset_x) <= SNAP_DISTANCE:
            if abs(seg.offset_y - other.offset_y) <= SNAP_DISTANCE or \
               abs(seg.offset_y + seg.height - (other.offset_y + other.height)) <= SNAP_DISTANCE:
                seg.offset_x = other.offset_x - seg.width

# ------------------------------
# Player camera focus
# ------------------------------
def get_player_focus(world, active_char=None):
    pcs = [c for c in world.characters if isinstance(c, PlayerCharacter)]
    if not pcs:
        return 0, 0

    focus = []

    for c in pcs:
        if c == active_char or c == world.characters[selected_char_index]:
            focus.append(c)
            continue

        if (player_camera.x <= c.x < player_camera.x + player_camera.width and
            player_camera.y <= c.y < player_camera.y + player_camera.height):
            focus.append(c)

    if not focus:
        return pcs[0].x, pcs[0].y

    x = sum(c.x for c in focus) // len(focus)
    y = sum(c.y for c in focus) // len(focus)
    return x, y


# ------------------------------
# DM Controls
# ------------------------------
def start_drag(event):
    global dragged_segment, seg_drag_offset

    if segment_manager_mode:
        # Try to grab a segment
        wx, wy = screen_to_tile(event, dm_camera)
        if wx is None:
            return

        for seg in world.map.segments:
            if (seg.offset_x <= wx < seg.offset_x + seg.width and
                seg.offset_y <= wy < seg.offset_y + seg.height):

                dragged_segment = seg
                seg_drag_offset = (wx - seg.offset_x, wy - seg.offset_y)
                return

    # Normal camera drag
    dm_camera.dragging = True
    dm_camera.drag_start = (event.x, event.y)
    dm_camera.cam_start = (dm_camera.x, dm_camera.y)


def drag(event):
    global dragged_segment

    if segment_manager_mode and dragged_segment:
        wx, wy = screen_to_tile(event, dm_camera)
        if wx is None:
            return

        # Move segment so cursor stays at same relative offset
        dragged_segment.offset_x = wx - seg_drag_offset[0]
        dragged_segment.offset_y = wy - seg_drag_offset[1]

        return


    # Normal camera dragging
    if dm_camera.dragging:
        dx_pixels = dm_camera.drag_start[0] - event.x
        dy_pixels = dm_camera.drag_start[1] - event.y

        dx_tiles = int(round(dx_pixels / tile_size))
        dy_tiles = int(round(dy_pixels / tile_size))

        dm_camera.x = dm_camera.cam_start[0] + dx_tiles
        dm_camera.y = dm_camera.cam_start[1] + dy_tiles
        dm_camera.clamp()

    if segment_manager_mode and dragged_segment:
        wx, wy = screen_to_tile(event, dm_camera)
        if wx is None:
            return
        dragged_segment.offset_x = wx - seg_drag_offset[0]
        dragged_segment.offset_y = wy - seg_drag_offset[1]

        # Snap to others
        snap_segment_to_others(dragged_segment, world.map.segments)


def end_drag(event):
    global dragged_segment

    if segment_manager_mode:
        dragged_segment = None
        return

    dm_camera.dragging = False
def get_image_offset(label, surface):
    """Return (ox, oy) = top-left pixel of the pygame surface inside the Tk label"""
    lw = label.winfo_width()
    lh = label.winfo_height()
    sw, sh = surface.get_size()

    ox = (lw - sw) // 2
    oy = (lh - sh) // 2
    return ox, oy

def screen_to_tile(event, camera):
    # Get offset of the rendered surface inside the Tk label
    ox, oy = get_image_offset(dm_label, dm_surface)

    # Mouse pixel relative to surface
    mx = event.x - ox
    my = event.y - oy

    # If clicked outside the rendered surface → ignore
    if mx < 0 or my < 0 or mx >= surface_width or my >= surface_height:
        return None, None

    # Pixel → screen tile
    sx = int(mx / tile_size)
    sy = int(my / tile_size)

    # Screen tile → world tile
    wx, wy = camera.screen_to_world(sx, sy)

    # Clamp
    wx = max(0, min(wx, world.map.width  - 1))
    wy = max(0, min(wy, world.map.height - 1))

    return wx, wy




def dm_click_move(event):
    char = world.characters[selected_char_index]

    # Ensure character is on a valid tile first
    snap_to_walkable(char, world)

    tx, ty = screen_to_tile(event, dm_camera)

    # If target tile not walkable, ignore
    tile = world.map.get_tile(tx, ty)
    if not tile or not tile.walkable:
        return

    path = []
    cx, cy = char.x, char.y

    # Safe Manhattan stepper
    max_steps = 500   # safety to prevent infinite loops
    steps = 0

    while (cx != tx or cy != ty) and steps < max_steps:
        steps += 1

        if cx < tx:
            step = (1, 0)
        elif cx > tx:
            step = (-1, 0)
        elif cy < ty:
            step = (0, 1)
        elif cy > ty:
            step = (0, -1)

        nx, ny = cx + step[0], cy + step[1]

        if world.map.can_move(cx, cy, nx, ny):
            path.append(step)
            cx, cy = nx, ny
        else:
            break   # hit wall or edge → stop cleanly

    char.move_queue = path



def dm_select_character(event):
    global selected_char_index

    for i, char in enumerate(world.characters):
        sx, sy = dm_camera.world_to_screen(char.x, char.y)
        px = sx * tile_size + tile_size // 2
        py = sy * tile_size + tile_size // 2
        radius = max(6, tile_size // 3)


        if (event.x - px)**2 + (event.y - py)**2 <= radius**2:
            selected_char_index = i
            break
def dm_toggle_segment(event):
    if not segment_manager_mode:
        return
    wx, wy = screen_to_tile(event, dm_camera)
    if wx is None:
        return
    for seg in world.map.segments:
        if seg.offset_x <= wx < seg.offset_x + seg.width and seg.offset_y <= wy < seg.offset_y + seg.height:
            seg.active = not seg.active
            print(f"{seg.name} active: {seg.active}")
            break


dm_label.bind("<Button-3>", dm_toggle_segment)
dm_label.bind("<Button-1>", start_drag)
dm_label.bind("<B1-Motion>", drag)
dm_label.bind("<ButtonRelease-1>", end_drag)
dm_label.bind("<Button-3>", dm_click_move)
dm_label.bind("<Button-2>", dm_select_character)


# ------------------------------
# Convert pygame → tkinter
# ------------------------------
def pygame_to_tk(surf):
    data = pygame.image.tostring(surf, "RGB")
    img = Image.frombytes("RGB", surf.get_size(), data)
    return ImageTk.PhotoImage(img)



# ------------------------------
# Update loop
# ------------------------------
def update():
    for char in world.characters:
        char.update_position(world)
        snap_to_walkable(char, world)

    px, py = get_player_focus(world, current_turn_char)
    player_camera.center_on(px, py)
    # Update fog before drawing
    update_fog_of_war(world, player_camera)

    renderer.draw(player_surface, world, player_camera, dm_view=False)
    renderer.draw(dm_surface, world, dm_camera, dm_view=True)

    player_img = pygame_to_tk(player_surface)
    dm_img = pygame_to_tk(dm_surface)

    player_label.img = player_img
    player_label.config(image=player_img)

    dm_label.img = dm_img
    dm_label.config(image=dm_img)

    player_win.after(50, update)


# ------------------------------
# Start
# ------------------------------
update()
player_win.mainloop()
