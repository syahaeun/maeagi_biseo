"""Pet movement states, independently implemented after reviewing Shimeji-ee.

See REFERENCE_REVIEW.md for the reference classes and attribution.
Velocities are logical pixels per 33 ms simulation tick.
"""
import random
import time

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from maeagi_biseo.resources import read_json
from maeagi_biseo.platforms.windows import WINDOW_TRACKER, landing_surface, crossed_surface, exposed

BEHAVIORS = read_json('behaviors.json')


class PetMotion:
    def init_motion(self, tracker=None):
        self.desktop_motion_enabled = True
        self.allowed_actions = None
        self.window_tracker = tracker if tracker is not None else WINDOW_TRACKER
        self.platform = None
        self.platform_rect = None
        self.motion = 'ground'
        self.vx = self.vy = 0.0
        self.paused = False
        self.wall_side = 0
        self.wall_down = False
        self.climb_requested = False
        self.drag_active = False
        self.drag_origin = None
        self.drag_samples = []

    def action_allowed(self, state):
        return self.allowed_actions is None or state in self.allowed_actions or state == 'idle'

    def set_allowed_actions(self, actions):
        self.allowed_actions = set(actions) | {'idle'}
        self.climb_requested = False
        if self.motion == 'wall' and not self.action_allowed('climb') or self.motion == 'ceiling' and not self.action_allowed('ceiling'):
            self.begin_fall()
        elif self.motion == 'ground' and not self.action_allowed(self.state):
            self.state = 'idle'
            self.state_until = time.monotonic()
        self.update()

    def choose(self):
        weights = {state: weight for state, weight in BEHAVIORS['selection']['weights'].items() if self.action_allowed(state)}
        state = random.choices(list(weights), list(weights.values()))[0]
        if self.focus:
            state = 'idle'
        self.state = state
        self.state_until = time.monotonic() + random.uniform(*BEHAVIORS['selection']['duration_seconds'])
        if state == 'walk':
            self.direction = random.choice([-1, 1])
        elif state == 'hop':
            self.start_jump()

    def tick(self):
        if self.drag_offset is not None:
            return
        if not self.desktop_motion_enabled:
            if not self.paused:
                self.phase += .12
            self.update()
            return
        if self.paused:
            if self.motion == 'ground':
                self.follow_platform()
                self.move(round(self.xpos), round(self.ypos))
            return
        self.phase += .12
        if self.motion == 'ground':
            self.follow_platform()
        if self.motion == 'air':
            self.step_air()
        elif self.motion == 'wall':
            self.step_wall()
        elif self.motion == 'ceiling':
            self.step_ceiling()
        elif self.motion == 'ground':
            if self.climb_requested and not self.focus:
                self.state = 'walk'
                self.state_until = float('inf')
            elif time.monotonic() > self.state_until:
                self.choose()
            if self.motion == 'ground' and self.state == 'walk':
                self.step_walk()
        self.move(round(self.xpos), round(self.ypos))
        self.update()

    def update_area(self, point=None):
        if point is None:
            point = QPoint(round(self.xpos + self.width()/2), round(self.ypos + self.foot_offset/2))
        screen = QApplication.screenAt(point)
        if screen is None:
            def distance(item):
                rect = item.availableGeometry()
                dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
                dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
                return dx*dx + dy*dy
            screen = min(QApplication.screens(), key=distance)
        self.area = screen.availableGeometry()

    def walk_bounds(self):
        rect = self.platform_rect if self.platform_rect is not None else self.area
        return max(self.area.left(), rect.left()), min(self.area.right(), rect.right()) - self.width() + 1

    def highest_standing_y(self):
        return self.area.top() - self.sprites.idle_top_margin

    def go_to_floor(self):
        """Explicit recovery action; ordinary loss of support uses gravity."""
        self.platform = self.platform_rect = None
        self.motion = 'ground'
        self.vx = self.vy = 0
        self.climb_requested = False
        self.update_area()
        self.xpos = max(self.area.left(), min(self.xpos, self.area.right() - self.width() + 1))
        self.ypos = float(self.area.bottom() + 1 - self.foot_offset)
        self.state = 'idle'
        self.state_until = time.monotonic() + 2
        self.move(round(self.xpos), round(self.ypos))

    def attach(self, surface, x=None):
        self.platform = surface.handle
        self.platform_rect = surface.rect
        self.motion = 'ground'
        self.vx = self.vy = 0
        if x is not None:
            self.xpos = x
        left, right = self.walk_bounds()
        if right < left:
            self.begin_fall()
            return
        self.xpos = max(left, min(self.xpos, right))
        self.ypos = float(surface.rect.top() - self.foot_offset)
        self.state = 'idle'
        self.state_until = time.monotonic() + 1.2

    def land(self, vx=0, vy=0):
        self.update_area()
        surfaces = self.window_tracker.snapshot(force=True)
        surface = landing_surface(surfaces, self.xpos + self.width()/2,
            self.ypos + self.foot_offset, self.width(), self.highest_standing_y() + self.foot_offset)
        if surface is not None:
            self.attach(surface)
        elif self.ypos + self.foot_offset >= self.area.bottom() + 1:
            self.touch_floor()
        else:
            self.begin_fall(vx, vy)
        self.move(round(self.xpos), round(self.ypos))

    def touch_floor(self):
        requested = self.climb_requested
        self.go_to_floor()
        self.climb_requested = requested

    def begin_fall(self, vx=0, vy=0):
        self.platform = self.platform_rect = None
        self.motion = 'air'
        self.vx, self.vy = float(vx), float(vy)
        self.state = 'fall'
        self.state_until = float('inf')

    def start_jump(self):
        if self.focus or self.paused or self.motion == 'air' or not self.action_allowed('hop'):
            return
        self.begin_fall(self.direction * BEHAVIORS['physics']['jump_horizontal_speed'],
                        -BEHAVIORS['physics']['jump_speed'])
        self.state = 'hop'

    def step_air(self):
        physics = BEHAVIORS['physics']
        old_x, old_y = self.xpos, self.ypos
        old_feet = old_y + self.foot_offset
        self.vx *= physics['air_friction']
        self.vy = min(physics['terminal_speed'], self.vy + physics['gravity'])
        self.xpos += self.vx
        self.ypos += self.vy
        self.update_area()
        self.xpos = max(self.area.left(), min(self.xpos, self.area.right() - self.width() + 1))
        highest_y = self.highest_standing_y()
        if self.ypos < highest_y:
            self.ypos = float(highest_y)
            self.vy = max(0, self.vy)
        if self.vy >= 0:
            surface, hit_x = crossed_surface(self.window_tracker.snapshot(),
                old_x + self.width()/2, old_feet,
                self.xpos + self.width()/2, self.ypos + self.foot_offset,
                self.width(), highest_y + self.foot_offset)
            if surface is not None:
                self.attach(surface, hit_x - self.width()/2)
                return
            if self.ypos + self.foot_offset >= self.area.bottom() + 1:
                self.touch_floor()

    def follow_platform(self):
        if self.motion != 'ground':
            return
        if self.platform is None:
            self.update_area()
            self.xpos = max(self.area.left(), min(self.xpos, self.area.right() - self.width() + 1))
            self.ypos = float(self.area.bottom() + 1 - self.foot_offset)
            return
        surfaces = self.window_tracker.snapshot()
        surface = next((item for item in surfaces if item.handle == self.platform), None)
        if surface is None or surface.rect.width() < self.width():
            self.begin_fall()
            return
        next_x = self.xpos + surface.rect.left() - self.platform_rect.left()
        self.update_area(QPoint(round(next_x + self.width()/2), surface.rect.top()))
        self.platform_rect = surface.rect
        left, right = self.walk_bounds()
        if right < left or surface.rect.top() < self.highest_standing_y() + self.foot_offset:
            self.begin_fall()
            return
        self.xpos = max(left, min(next_x, right))
        if not exposed(surface, surfaces, self.xpos + self.width()/2):
            self.begin_fall()
            return
        self.ypos = float(surface.rect.top() - self.foot_offset)

    def step_walk(self):
        left, right = self.walk_bounds()
        self.xpos += self.direction * BEHAVIORS['movement']['walk_speed']
        if self.xpos < left or self.xpos > right:
            self.xpos = max(left, min(self.xpos, right))
            if self.climb_requested and self.platform is not None and self.action_allowed('hop'):
                self.start_jump()
                self.vx = self.direction * 5
            elif self.platform is None and not self.focus and self.action_allowed('climb') and BEHAVIORS['movement']['climb_enabled'] and (
                    self.climb_requested or random.random() < BEHAVIORS['movement']['auto_climb_probability']):
                self.attach_wall(-1 if self.direction < 0 else 1)
            else:
                self.direction *= -1

    def request_climb(self):
        if self.focus or self.paused or not self.action_allowed('climb') or not self.action_allowed('walk') or not BEHAVIORS['movement']['climb_enabled']:
            return
        self.climb_requested = True
        self.direction = -1 if self.xpos - self.area.left() < self.area.right() - self.xpos else 1

    def attach_wall(self, side, down=False):
        if not self.action_allowed('climb'):
            self.begin_fall()
            return
        self.platform = self.platform_rect = None
        self.climb_requested = False
        self.motion, self.state = 'wall', 'climb'
        self.wall_side, self.wall_down = side, down
        self.direction = side
        self.xpos = float(self.area.left() if side < 0 else self.area.right() - self.width() + 1)
        self.state_until = time.monotonic() + random.uniform(*BEHAVIORS['selection']['wall_duration_seconds'])

    def step_wall(self):
        previous_area = self.area
        self.update_area()
        if self.area != previous_area or self.focus or time.monotonic() > self.state_until:
            self.begin_fall(-self.wall_side * 2)
            return
        self.ypos += BEHAVIORS['movement']['climb_speed'] * (1 if self.wall_down else -1)
        if self.wall_down and self.ypos + self.foot_offset >= self.area.bottom() + 1:
            self.touch_floor()
        elif self.ypos <= self.area.top():
            self.ypos = float(self.area.top())
            if not self.action_allowed('ceiling'):
                self.begin_fall(-self.wall_side * 2)
                return
            self.motion, self.state = 'ceiling', 'ceiling'
            self.direction = -self.wall_side
            self.state_until = time.monotonic() + random.uniform(*BEHAVIORS['selection']['ceiling_duration_seconds'])

    def step_ceiling(self):
        previous_area = self.area
        self.update_area()
        if self.area != previous_area or self.focus or time.monotonic() > self.state_until:
            self.begin_fall(self.direction * 2)
            return
        self.xpos += self.direction * BEHAVIORS['movement']['ceiling_speed']
        if self.xpos <= self.area.left():
            self.attach_wall(-1, down=True)
        elif self.xpos >= self.area.right() - self.width() + 1:
            self.attach_wall(1, down=True)

    def set_paused(self, value):
        self.paused = value

    def set_desktop_motion(self, enabled):
        enabled = bool(enabled)
        if enabled != self.desktop_motion_enabled:
            self.desktop_motion_enabled = enabled
            self.state = 'idle'
            self.state_until = time.monotonic() + 1

    def can_talk(self):
        return self.action_allowed('talk') and (self.motion == 'ground' or not self.desktop_motion_enabled) and self.drag_offset is None and not self.paused and not self.focus

    def record_drag(self):
        now = time.monotonic()
        self.drag_samples.append((now, self.xpos, self.ypos))
        self.drag_samples = [sample for sample in self.drag_samples[-6:] if now - sample[0] <= .15]

    def release_velocity(self):
        if not BEHAVIORS['movement']['throw_enabled'] or len(self.drag_samples) < 2:
            return 0, 0
        first, last = self.drag_samples[0], self.drag_samples[-1]
        if time.monotonic() - last[0] > .12:
            return 0, 0
        elapsed = max(.01, last[0] - first[0])
        maximum = BEHAVIORS['physics']['throw_max_speed']
        return tuple(max(-maximum, min(maximum, (last[index] - first[index]) / elapsed / 30))
                     for index in (1, 2))
