"""Pygame drawing shared by play.py and replay.py."""

import math

import pygame

import config

BG = (14, 16, 26)
FIELD_BG = (22, 25, 40)
OUTSIDE_BG = (17, 19, 30)     # visible area beyond the walls
WALL = (200, 70, 70)
GOAL = (70, 210, 120)
GATE_WALL = (200, 70, 70)
GRID = (32, 36, 56)
SHIP = (235, 235, 245)
SHIP_INVULN = (255, 210, 80)
FLAME = (255, 150, 40)
ASTEROID = (150, 140, 130)
ASTEROID_EDGE = (95, 88, 80)
ASTEROID_SPENT = (60, 58, 62)
TEXT = (225, 228, 240)
DIM = (140, 145, 165)
GOOD = (110, 225, 140)
BAD = (240, 100, 100)
VEL = (90, 170, 255)
TRAIL = (90, 110, 170)

MARGIN = 24


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_angle(a, b, t):
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + d * t


class Renderer:
    def __init__(self, settings, caption="Asteroid Field"):
        self.s = settings
        self.ppu = config.PIXELS_PER_UNIT
        pygame.display.set_caption(caption)
        self._layout()
        self.screen = pygame.display.set_mode(self.size)
        self.font = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 20)
        self.font_big = pygame.font.Font(None, 44)

    def _layout(self):
        s = self.s
        self.W, self.H = s["FIELD_WIDTH"], s["FIELD_HEIGHT"]
        self.vm = s.get("VIEW_MARGIN_FRAC", 0.0) * self.W
        ppu = self.ppu
        self.view_px = (int((self.W + 2 * self.vm) * ppu), int((self.H + 2 * self.vm) * ppu))
        self.field_rect = pygame.Rect(self.to_px(0, self.H),
                                      (int(self.W * ppu), int(self.H * ppu)))
        self.view_rect = pygame.Rect(MARGIN, MARGIN, *self.view_px)
        self.size = (self.view_px[0] + 2 * MARGIN + config.HUD_WIDTH,
                     self.view_px[1] + 2 * MARGIN)
        self.hud_x = self.view_px[0] + 2 * MARGIN + 10

    def set_settings(self, settings):
        self.s = settings
        old = self.size
        self._layout()
        if self.size != old:
            self.screen = pygame.display.set_mode(self.size)

    # -- coordinates ---------------------------------------------------------
    def to_px(self, x, y):
        return (int(MARGIN + (x + self.vm) * self.ppu),
                int(MARGIN + (self.H + self.vm - y) * self.ppu))

    # -- field ---------------------------------------------------------------
    def draw_field(self):
        """Background: the visible margin, the playfield, and its grid."""
        self.screen.fill(BG)
        pygame.draw.rect(self.screen, OUTSIDE_BG, self.view_rect)
        pygame.draw.rect(self.screen, GRID, self.view_rect, 1)
        fr = self.field_rect
        pygame.draw.rect(self.screen, FIELD_BG, fr)
        step = 0.25
        for i in range(1, int(self.W / step) + 1):
            x = self.to_px(i * step, 0)[0]
            if x < fr.right:
                pygame.draw.line(self.screen, GRID, (x, fr.top), (x, fr.bottom))
        for i in range(1, int(self.H / step) + 1):
            y = self.to_px(0, i * step)[1]
            if y > fr.top:
                pygame.draw.line(self.screen, GRID, (fr.left, y), (fr.right, y))
        sx, sy = self.s["START_POS"]
        pygame.draw.circle(self.screen, GRID, self.to_px(sx, sy),
                           int(self.s["SHIP_RADIUS"] * self.ppu * 1.8), 1)

    def draw_walls(self):
        """Walls and goal - drawn after the asteroids so they stay visible."""
        tl, tr = self.to_px(0, self.H), self.to_px(self.W, self.H)
        bl, br = self.to_px(0, 0), self.to_px(self.W, 0)
        pygame.draw.line(self.screen, WALL, tl, bl, 4)
        pygame.draw.line(self.screen, WALL, tr, br, 4)
        bottom_color = WALL if self.s["BOTTOM_IS_WALL"] else DIM
        pygame.draw.line(self.screen, bottom_color, bl, br, 4)
        gate = self.s["GOAL_GATE"]
        if gate is None:
            pygame.draw.line(self.screen, GOAL, tl, tr, 6)
        else:
            cx, w = gate
            g0, g1 = self.to_px(cx - w / 2, self.H), self.to_px(cx + w / 2, self.H)
            pygame.draw.line(self.screen, GATE_WALL, tl, g0, 4)
            pygame.draw.line(self.screen, GATE_WALL, g1, tr, 4)
            pygame.draw.line(self.screen, GOAL, g0, g1, 8)

    # -- objects -------------------------------------------------------------
    def _clip(self):
        self.screen.set_clip(self.view_rect)

    def draw_asteroids(self, asteroids, show_ids=False):
        self._clip()
        for a in asteroids:
            p = self.to_px(a["x"], a["y"])
            r = max(2, int(a["r"] * self.ppu))
            if a.get("spent"):      # already hit the ship: harmless, drawn dim
                pygame.draw.circle(self.screen, ASTEROID_SPENT, p, r)
                pygame.draw.circle(self.screen, ASTEROID_EDGE, p, r, 1)
            else:
                pygame.draw.circle(self.screen, ASTEROID, p, r)
                pygame.draw.circle(self.screen, ASTEROID_EDGE, p, r, 2)
            if show_ids:
                t = self.font_small.render(str(a["id"]), True, TEXT)
                self.screen.blit(t, t.get_rect(center=p))
        self.screen.set_clip(None)

    def draw_trail(self, trail):
        if len(trail) > 1:
            self._clip()
            pygame.draw.lines(self.screen, TRAIL, False, [self.to_px(x, y) for x, y in trail], 1)
            self.screen.set_clip(None)

    def draw_ship(self, ship, thrusting=False, invulnerable=False, t=0.0, show_vel=True):
        x, y, h = ship["x"], ship["y"], ship["heading"]
        r = self.s["SHIP_RADIUS"]
        if invulnerable and int(t * 10) % 2 == 0:
            color = SHIP_INVULN
        else:
            color = SHIP
        nose = (x + 1.6 * r * math.cos(h), y + 1.6 * r * math.sin(h))
        left = (x + r * math.cos(h + 2.5), y + r * math.sin(h + 2.5))
        right = (x + r * math.cos(h - 2.5), y + r * math.sin(h - 2.5))
        back = (x - 0.5 * r * math.cos(h), y - 0.5 * r * math.sin(h))
        if thrusting:
            flame = (x - 1.9 * r * math.cos(h), y - 1.9 * r * math.sin(h))
            fl = (x + 0.55 * r * math.cos(h + 2.2), y + 0.55 * r * math.sin(h + 2.2))
            fr = (x + 0.55 * r * math.cos(h - 2.2), y + 0.55 * r * math.sin(h - 2.2))
            pygame.draw.polygon(self.screen, FLAME, [self.to_px(*p) for p in (fl, flame, fr)])
        pygame.draw.polygon(self.screen, color, [self.to_px(*p) for p in (nose, left, back, right)])
        pygame.draw.circle(self.screen, (70, 75, 100), self.to_px(x, y), int(r * self.ppu), 1)
        if show_vel:
            vx, vy = ship["vx"], ship["vy"]
            end = (x + vx * 1.0, y + vy * 1.0)   # where you'll be in 1 s
            pygame.draw.line(self.screen, VEL, self.to_px(x, y), self.to_px(*end), 2)

    # -- text ----------------------------------------------------------------
    def text(self, s, pos, color=TEXT, font=None, center=False):
        surf = (font or self.font).render(s, True, color)
        rect = surf.get_rect(center=pos) if center else surf.get_rect(topleft=pos)
        self.screen.blit(surf, rect)
        return rect

    def hud(self, lines, y0=MARGIN):
        """lines: list of (text, color) or None for a spacer."""
        y = y0
        for item in lines:
            if item is None:
                y += 10
                continue
            s, c = item
            f = self.font_small if c == DIM else self.font
            self.text(s, (self.hud_x, y), c, f)
            y += 24 if f is self.font else 20

    def overlay(self, title, lines, title_color=TEXT):
        fr = self.field_rect
        panel = pygame.Surface((max(fr.width, 380), 60 + 28 * len(lines)), pygame.SRCALPHA)
        panel.fill((10, 12, 20, 215))
        rect = panel.get_rect(center=fr.center)
        self.screen.blit(panel, rect)
        self.text(title, (rect.centerx, rect.top + 30), title_color, self.font_big, center=True)
        for i, ln in enumerate(lines):
            self.text(ln, (rect.centerx, rect.top + 70 + 28 * i), TEXT, center=True)


def interpolate_state(prev, cur, alpha):
    """Blend two get_state()-style dicts for smooth drawing between ticks."""
    if prev is None or alpha >= 1:
        return cur
    ps, cs = prev["ship"], cur["ship"]
    ship = dict(cs)
    ship["x"] = lerp(ps["x"], cs["x"], alpha)
    ship["y"] = lerp(ps["y"], cs["y"], alpha)
    ship["heading"] = lerp_angle(ps["heading"], cs["heading"], alpha)
    prev_ast = {a["id"]: a for a in prev["asteroids"]}
    asts = []
    for a in cur["asteroids"]:
        p = prev_ast.get(a["id"])
        if p is None:
            asts.append(a)
        else:
            b = dict(a)
            b["x"] = lerp(p["x"], a["x"], alpha)
            b["y"] = lerp(p["y"], a["y"], alpha)
            asts.append(b)
    out = dict(cur)
    out["ship"] = ship
    out["asteroids"] = asts
    return out
