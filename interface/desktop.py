"""
JARVIS 3D Holographic Celestial Goddess Interface.

State-of-the-art OpenGL 3.3 Core Profile celestial entity visualizer:
- Cosmic stardust female goddess rendered with 100,000+ glowing particles and constellation filaments
- Brilliant 4-point radiant diamond starburst on the forehead (ajna / third eye chakra)
- Luminous sacred geometry star mandala centered on the sternum with radiating rays
- Deep royal blue and electric sapphire/cyan stardust highlights
- Billowing cosmic nebula wings enveloping the shoulders
- Ethereal luminous glowing eyes looking forward with sharp intelligence
- Full interactive 3D orbit mouse controls (drag to rotate, scroll/right-drag to zoom, double-click reset)
- Audio-reactive vocal synthesis waves & pulse expansion on speech
- Minimalist cybernetic telemetry HUD overlay with subtitle display
- Direct FULL_CONTROL permissions integration
"""

import sys
import queue
import os
import json
import math
import ctypes
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, Slot, QThread, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from OpenGL.GL import *

# -------------------------------------------------------------
# SHADERS: Celestial Cosmic Goddess Particles & Constellations
# -------------------------------------------------------------
VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec4 in_color;
layout(location = 2) in float in_size;
layout(location = 3) in float in_type;

uniform mat4 u_mvp;
uniform float u_time;
uniform float u_breathing;
uniform int u_state;
uniform float u_scanline_pos;
uniform float u_vocal_energy;

out vec4 v_color;
out vec3 v_world_pos;
out float v_type;
out float v_scanline_factor;

void main() {
    vec3 p = in_position;

    // Organic harmonic celestial breathing
    float breath = sin(u_time * 1.5 + p.y * 0.02) * 0.008 * (1.0 + u_breathing);
    p *= (1.0 + breath);

    // Audio-reactive pulse for heart mandala (type 3.0) and third eye (type 2.0)
    if (abs(in_type - 3.0) < 0.4) {
        float pulse = sin(u_time * 4.0) * 0.025 + u_vocal_energy * 0.08;
        p += normalize(p - vec3(0.0, -18.0, 15.0)) * (pulse * 3.5);
    } else if (abs(in_type - 2.0) < 0.4) {
        float pulse = sin(u_time * 5.0) * 0.02 + u_vocal_energy * 0.05;
        p += normalize(p - vec3(0.0, 77.0, 31.5)) * (pulse * 2.0);
    } else if (abs(in_type - 4.0) < 0.4) {
        // Cosmic nebula drift
        p.x += sin(u_time * 0.6 + p.y * 0.015) * 1.5;
        p.y += cos(u_time * 0.5 + p.x * 0.015) * 1.2;
    }

    v_world_pos = p;
    v_type = in_type;

    vec4 col = in_color;

    // State color shifts
    if (u_state == 1) { // listening (cyan bloom)
        col.rgb = mix(col.rgb, vec3(0.25, 1.1, 1.6), 0.35);
        col.a = min(col.a * 1.25, 1.0);
    } else if (u_state == 2) { // thinking (violet/deep celestial shift)
        if (abs(in_type - 2.0) < 0.4 || p.y > 45.0) {
            col.rgb *= 1.4;
            col.a = min(col.a * 1.3, 1.0);
        } else {
            col.rgb = mix(col.rgb, vec3(0.7, 0.45, 1.8), 0.35);
        }
    } else if (u_state == 3) { // speaking (luminous energy wave)
        if (abs(in_type - 3.0) < 0.4 || abs(in_type - 1.0) < 0.4) {
            col.rgb += vec3(0.35, 0.8, 1.5) * u_vocal_energy;
        }
    }

    float dist_scan = abs(p.y - u_scanline_pos);
    v_scanline_factor = exp(-dist_scan * dist_scan * 0.0025);

    gl_Position = u_mvp * vec4(p, 1.0);

    float base_size = in_size;
    if (abs(in_type - 2.0) < 0.4) {
        base_size *= (1.08 + sin(u_time * 4.0) * 0.12 + u_vocal_energy * 0.25);
    } else if (abs(in_type - 3.0) < 0.4) {
        base_size *= (1.08 + sin(u_time * 3.0) * 0.12 + u_vocal_energy * 0.20);
    }

    gl_PointSize = clamp(base_size * (640.0 / gl_Position.w), 1.0, 52.0);
    v_color = col;
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec4 v_color;
in vec3 v_world_pos;
in float v_type;
in float v_scanline_factor;

out vec4 FragColor;
uniform int u_is_point;

void main() {
    if (u_is_point == 1) {
        vec2 coord = gl_PointCoord - vec2(0.5);
        float dist = length(coord);
        if (dist > 0.5) discard;

        // Diamond star core + soft radiant stardust bloom
        float core = 1.0 - smoothstep(0.0, 0.15, dist);
        float halo = 1.0 - smoothstep(0.04, 0.5, dist);
        float alpha = core * 1.6 + halo * 0.75;

        float intensity = 1.05;
        if (abs(v_type - 2.0) < 0.4) {
            intensity = 1.65;
        } else if (abs(v_type - 3.0) < 0.4) {
            intensity = 1.40;
        } else if (abs(v_type - 1.0) < 0.4) {
            intensity = 1.30;
        }

        vec3 out_rgb = v_color.rgb * (intensity + core * 1.15) + vec3(0.18, 0.45, 0.85) * v_scanline_factor * 0.25;
        FragColor = vec4(out_rgb, min(1.0, v_color.a * alpha));
    } else {
        FragColor = vec4(v_color.rgb + vec3(0.18, 0.45, 0.85) * v_scanline_factor * 0.25, v_color.a);
    }
}
"""

# -------------------------------------------------------------
# Event Bridge: Listens to JARVIS Manager and Forwards to UI
# -------------------------------------------------------------
class EventListenerThread(QThread):
    event_received = Signal(object)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.running = True

    def run(self):
        if not self.manager:
            return
        q = self.manager.events.subscribe()
        while self.running:
            try:
                raw_evt = q.get(timeout=0.5)
                if isinstance(raw_evt, str):
                    try:
                        evt = json.loads(raw_evt)
                    except Exception:
                        continue
                else:
                    evt = raw_evt
                self.event_received.emit(evt)
            except queue.Empty:
                continue

    def stop(self):
        self.running = False
        self.wait()


# -------------------------------------------------------------
# Geometry Generator: Celestial Goddess Particles & Constellations
# -------------------------------------------------------------
def generate_goddess_geometry():
    model_path = os.path.join(os.path.dirname(__file__), "..", "female02_clean.obj")
    if not os.path.exists(model_path):
        model_path = os.path.join(os.path.dirname(__file__), "..", "female02.obj")

    raw_v, raw_f = [], []
    with open(model_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('v '):
                raw_v.append([float(x) for x in line.split()[1:4]])
            elif line.startswith('f '):
                p = line.split()
                try:
                    raw_f.append([int(p[1].split('/')[0]) - 1, int(p[2].split('/')[0]) - 1, int(p[3].split('/')[0]) - 1])
                except Exception:
                    pass

    v = np.array(raw_v, dtype=np.float32)
    f = np.array(raw_f, dtype=np.uint32)

    # Filter bust: from mid-chest (y > 115) to cranium (y ~ 168)
    mask_v = v[:, 1] > 115.0
    face_mask = np.sum(mask_v[f], axis=1) == 3
    f_bust = f[face_mask]

    # Center midline on x = 2.538 (nose tip / facial symmetry line)
    v_used = v.copy()
    v_used[:, 0] -= 2.538

    # Center Y around clavicles/neck (y ~ 138)
    y_center = 138.0
    z_center = 6.0
    scale = 3.6

    v_used[:, 0] = v_used[:, 0] * scale
    v_used[:, 1] = (v_used[:, 1] - y_center) * scale
    v_used[:, 2] = (v_used[:, 2] - z_center) * scale

    # 1. Surface Stardust Points (58,000 particles)
    v0 = v_used[f_bust[:, 0]]
    v1 = v_used[f_bust[:, 1]]
    v2 = v_used[f_bust[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    probs = areas / (areas.sum() + 1e-7)

    n_samples = 58000
    chosen = np.random.choice(len(f_bust), size=n_samples, p=probs)
    r1 = np.random.rand(n_samples, 1).astype(np.float32)
    r2 = np.random.rand(n_samples, 1).astype(np.float32)
    mask = (r1 + r2) > 1.0
    r1[mask] = 1.0 - r1[mask]
    r2[mask] = 1.0 - r2[mask]
    r3 = 1.0 - r1 - r2
    surf_pts = r1 * v0[chosen] + r2 * v1[chosen] + r3 * v2[chosen]
    surf_pts += np.random.randn(*surf_pts.shape).astype(np.float32) * 0.20

    # Organic soft fade at the bottom of the portrait
    y_fade = np.clip((surf_pts[:, 1] - (-75.0)) / 30.0, 0.0, 1.0)

    # Base stardust color: deep royal celestial blue
    surf_cols = np.zeros((n_samples, 4), dtype=np.float32)
    surf_cols[:, 0] = 0.12
    surf_cols[:, 1] = 0.28
    surf_cols[:, 2] = 1.08
    surf_cols[:, 3] = 0.18 * y_fade

    # Facial highlights: nose ridge, cheekbones, lips, jawline
    face_zone = (surf_pts[:, 2] > 14.0) & (surf_pts[:, 1] > 15.0)
    surf_cols[face_zone, 0] += 0.22
    surf_cols[face_zone, 1] += 0.42
    surf_cols[face_zone, 2] += 0.52
    surf_cols[face_zone, 3] = np.minimum(0.92, surf_cols[face_zone, 3] * 1.85)

    nose_lips = (surf_pts[:, 2] > 26.5) & (abs(surf_pts[:, 0]) < 7.5)
    surf_cols[nose_lips, 0] += 0.22
    surf_cols[nose_lips, 1] += 0.38
    surf_cols[nose_lips, 2] += 0.45

    surf_szs = np.random.uniform(1.6, 3.4, (n_samples, 1)).astype(np.float32)
    surf_types = np.zeros((n_samples, 1), dtype=np.float32)

    # 2. Natural Radiant Celestial Eyes (type 1.0)
    eye_pts, eye_cols, eye_szs, eye_types = [], [], [], []
    for side in (-10.0, 10.0):
        center = np.array([side, 61.5, 27.5], dtype=np.float32)
        # Soft iris stardust halo (celestial blue/violet)
        for _ in range(70):
            rad = np.random.uniform(0.2, 2.8)
            ang = np.random.uniform(0, 2 * np.pi)
            x_p = center[0] + rad * np.cos(ang) * 1.2
            y_p = center[1] + rad * np.sin(ang) * 0.75
            z_p = center[2] + 0.3
            eye_pts.append([x_p, y_p, z_p])
            eye_cols.append([0.8, 1.4, 3.0, 0.45])
            eye_szs.append([np.random.uniform(1.8, 3.2)])
            eye_types.append([1.0])

        # Eye socket subtle starry contour
        for t in np.linspace(-1.0, 1.0, 30):
            x_off = t * 6.0
            y_up = center[1] + (1.0 - t**2) * 2.2
            y_dn = center[1] - (1.0 - t**2) * 1.4
            eye_pts.append([center[0] + x_off, y_up, center[2]])
            eye_cols.append([0.6, 1.1, 2.4, 0.35])
            eye_szs.append([2.0])
            eye_types.append([1.0])

            eye_pts.append([center[0] + x_off, y_dn, center[2]])
            eye_cols.append([0.4, 0.8, 2.0, 0.25])
            eye_szs.append([1.8])
            eye_types.append([1.0])

        # Pupil glowing diamond star (sharp and luminous)
        eye_pts.append([center[0], center[1], center[2] + 0.6])
        eye_cols.append([3.2, 3.4, 4.0, 1.0])
        eye_szs.append([5.2])
        eye_types.append([1.0])

    # 3. Third-Eye / Ajna Starburst (type 2.0)
    third_pts, third_cols, third_szs, third_types = [], [], [], []
    te_center = np.array([0.0, 77.0, 31.5], dtype=np.float32)

    # Core star singularity
    for _ in range(45):
        rad = np.random.uniform(0.05, 1.6)
        ang = np.random.uniform(0, 2 * np.pi)
        third_pts.append([te_center[0] + rad * np.cos(ang), te_center[1] + rad * np.sin(ang), te_center[2] + np.random.normal(0, 0.15)])
        third_cols.append([3.6, 3.7, 4.0, 1.0])
        third_szs.append([np.random.uniform(4.0, 7.5)])
        third_types.append([2.0])

    # 4-point Diamond Diffraction Cross Rays
    for x_off in np.linspace(-35.0, 35.0, 140):
        t = abs(x_off) / 35.0
        decay = (1.0 - t)**1.6
        third_pts.append([te_center[0] + x_off, te_center[1] + np.random.normal(0, 0.15 * decay), te_center[2] + np.random.normal(0, 0.08)])
        third_cols.append([2.4 * decay, 2.7 * decay, 3.6, 0.85 * decay])
        third_szs.append([max(1.4, 6.5 * decay)])
        third_types.append([2.0])

    for y_off in np.linspace(-28.0, 28.0, 120):
        t = abs(y_off) / 28.0
        decay = (1.0 - t)**1.6
        third_pts.append([te_center[0] + np.random.normal(0, 0.15 * decay), te_center[1] + y_off, te_center[2] + np.random.normal(0, 0.08)])
        third_cols.append([2.4 * decay, 2.7 * decay, 3.6, 0.85 * decay])
        third_szs.append([max(1.4, 6.5 * decay)])
        third_types.append([2.0])

    for diag in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        for s in np.linspace(1.0, 16.0, 32):
            t = s / 16.0
            decay = (1.0 - t)**1.8
            third_pts.append([te_center[0] + diag[0] * s * 0.7, te_center[1] + diag[1] * s * 0.7, te_center[2] - s * 0.04])
            third_cols.append([1.2 * decay, 1.8 * decay, 2.8, 0.45 * decay])
            third_szs.append([max(1.1, 3.8 * decay)])
            third_types.append([2.0])

    # 4. Sacred Heart / Sternum Star Mandala (type 3.0)
    heart_pts, heart_cols, heart_szs, heart_types = [], [], [], []
    h_center = np.array([0.0, -18.0, 22.0], dtype=np.float32)

    for _ in range(40):
        rad = np.random.uniform(0.1, 2.0)
        ang = np.random.uniform(0, 2 * np.pi)
        heart_pts.append([h_center[0] + rad * np.cos(ang), h_center[1] + rad * np.sin(ang), h_center[2] + np.random.normal(0, 0.25)])
        heart_cols.append([3.6, 3.7, 4.0, 1.0])
        heart_szs.append([np.random.uniform(4.5, 8.5)])
        heart_types.append([3.0])

    for ray_idx in range(12):
        ang = ray_idx * (2 * np.pi / 12.0)
        for r_len in np.linspace(2.5, 26.0, 26):
            t_r = (r_len - 2.5) / 23.5
            decay = (1.0 - t_r)**1.2
            heart_pts.append([
                h_center[0] + r_len * np.cos(ang),
                h_center[1] + r_len * np.sin(ang) * 0.9,
                h_center[2] - r_len * 0.08
            ])
            heart_cols.append([0.75 * decay, 1.35 * decay, 2.8, 0.48 * decay])
            heart_szs.append([max(1.4, 4.5 * decay)])
            heart_types.append([3.0])

    for r in [4.5, 9.5, 16.0, 25.0]:
        num_th = int(r * 9)
        for th in np.linspace(0, 2 * np.pi, num_th):
            heart_pts.append([
                h_center[0] + r * np.cos(th),
                h_center[1] + r * np.sin(th) * 0.88,
                h_center[2] - r * 0.05
            ])
            heart_cols.append([0.35, 0.90, 2.4, 0.22])
            heart_szs.append([np.random.uniform(1.4, 2.6)])
            heart_types.append([3.0])

    # 5. Billowing Cosmic Nebula Wings (type 4.0)
    dust_pts, dust_cols, dust_szs, dust_types = [], [], [], []
    num_dust = 42000
    for _ in range(num_dust):
        side = -1.0 if np.random.rand() > 0.5 else 1.0
        u = np.random.rand()
        th = -0.40 + u * 1.80
        r_dist = 16.0 + (np.random.rand()**1.2) * 118.0
        x = side * (14.0 + r_dist * np.cos(th) + np.random.normal(0, 2.2))
        y = -25.0 + r_dist * np.sin(th) * 0.82 + np.random.normal(0, 2.5)
        z = 2.0 - (r_dist / 75.0)**1.3 * 30.0 + np.random.normal(0, 4.5)

        dist_factor = min(1.0, abs(x) / 125.0)
        alpha = (0.16 + (1.0 - dist_factor) * 0.12) * np.clip((y - (-80.0)) / 40.0, 0.0, 1.0)
        dust_pts.append([x, y, z])
        dust_cols.append([0.12 + dist_factor * 0.18, 0.26 + (1.0 - dist_factor) * 0.32, 1.18 + dist_factor * 0.3, alpha])
        dust_szs.append([np.random.uniform(1.4, 3.2)])
        dust_types.append([4.0])

    # Crown halo dome
    crown_center = np.array([0.0, 80.0, 0.0], dtype=np.float32)
    for _ in range(9500):
        phi = np.random.uniform(0, 2 * np.pi)
        costheta = np.random.uniform(0.1, 1.0)
        sintheta = np.sqrt(1.0 - costheta**2)
        rad = np.random.uniform(22.0, 48.0)
        x = crown_center[0] + rad * sintheta * np.cos(phi) * 0.95
        y = crown_center[1] + rad * costheta * 1.15
        z = crown_center[2] + rad * sintheta * np.sin(phi) * 0.75
        dust_pts.append([x, y, z])
        dist_c = (rad - 22.0) / 26.0
        alpha = (1.0 - dist_c) * 0.22
        dust_cols.append([0.18, 0.42, 1.35, alpha])
        dust_szs.append([np.random.uniform(1.3, 2.8)])
        dust_types.append([4.0])

    # Combine all point sets
    all_p = [surf_pts]
    all_c = [surf_cols]
    all_s = [surf_szs]
    all_t = [surf_types]

    for pts, cols, szs, types in [
        (eye_pts, eye_cols, eye_szs, eye_types),
        (third_pts, third_cols, third_szs, third_types),
        (heart_pts, heart_cols, heart_szs, heart_types),
        (dust_pts, dust_cols, dust_szs, dust_types)
    ]:
        all_p.append(np.array(pts, dtype=np.float32))
        all_c.append(np.array(cols, dtype=np.float32))
        all_s.append(np.array(szs, dtype=np.float32))
        all_t.append(np.array(types, dtype=np.float32))

    points_data = np.ascontiguousarray(
        np.hstack([np.vstack(all_p), np.vstack(all_c), np.vstack(all_s), np.vstack(all_t)]),
        dtype=np.float32
    )

    # 6. Constellation Network Lines (Neck, Clavicles, Cranium)
    lines = []
    for x_side in (-4.0, 0.0, 4.0):
        for y_seg in range(-18, 48, 5):
            lines.append([x_side, float(y_seg), 22.0 - abs(y_seg) * 0.1])
            lines.append([x_side, float(y_seg + 5), 22.0 - abs(y_seg + 5) * 0.1])

    for side in (-1.0, 1.0):
        for step in range(12):
            s1 = step / 12.0
            s2 = (step + 1) / 12.0
            p1 = [side * (s1 * 36.0), -12.0 - s1**1.5 * 8.0, 18.0 - s1 * 12.0]
            p2 = [side * (s2 * 36.0), -12.0 - s2**1.5 * 8.0, 18.0 - s2 * 12.0]
            lines.append(p1)
            lines.append(p2)

    upper_mask = (surf_pts[:, 1] > 30.0) & (surf_pts[:, 2] > -10.0)
    upper_pts = surf_pts[upper_mask]
    if len(upper_pts) > 600:
        chosen_idx = np.random.choice(len(upper_pts), 600, replace=False)
        subset = upper_pts[chosen_idx]
        for i in range(len(subset)):
            dists = np.linalg.norm(subset - subset[i], axis=1)
            close = np.where((dists > 3.0) & (dists < 9.0))[0]
            for c in close[:2]:
                if c > i:
                    lines.append(subset[i])
                    lines.append(subset[c])

    if lines:
        l_arr = np.array(lines, dtype=np.float32)
        n_l = len(l_arr)
        l_fade = np.clip((l_arr[:, 1] - (-70.0)) / 30.0, 0.0, 1.0)
        l_cols = np.zeros((n_l, 4), dtype=np.float32)
        l_cols[:, 0] = 0.20
        l_cols[:, 1] = 0.52
        l_cols[:, 2] = 1.50
        l_cols[:, 3] = 0.26 * l_fade
        l_szs = np.ones((n_l, 1), dtype=np.float32)
        l_types = np.full((n_l, 1), 5.0, dtype=np.float32)
        lines_data = np.ascontiguousarray(np.hstack([l_arr, l_cols, l_szs, l_types]), dtype=np.float32)
    else:
        lines_data = np.zeros((0, 9), dtype=np.float32)

    return points_data, lines_data


# -------------------------------------------------------------
# 3D Celestial Goddess OpenGL Widget
# -------------------------------------------------------------
class CelestialGoddessGL(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(600, 720)
        self.state = "idle"
        self.time = 0.0
        self._gl_ready = False

        # Front portrait view matching image 2
        self.rot_x = 0.0
        self.rot_y = 0.0
        self.target_rot_x = 0.0
        self.target_rot_y = 0.0
        self.zoom = -230.0
        self.target_zoom = -230.0
        self._drag_start = None

        # Scanline and vocal state
        self.scanline_y = 70.0
        self.vocal_energy = 0.0
        self.target_vocal_energy = 0.0

        self.points_buffer, self.lines_buffer = generate_goddess_geometry()
        self.num_points = len(self.points_buffer)
        self.num_lines = len(self.lines_buffer)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(16)

    def initializeGL(self):
        try:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE) # Additive celestial bloom
            glEnable(GL_PROGRAM_POINT_SIZE)
            try:
                glEnable(0x8861) # GL_POINT_SPRITE
                glTexEnvi(0x8861, 0x8862, GL_TRUE) # GL_COORD_REPLACE
            except Exception:
                pass
            glDisable(GL_DEPTH_TEST)
            glClearColor(0.002, 0.004, 0.012, 1.0) # Pitch-black space void

            self.program = self._compile_shader_program(VERTEX_SHADER, FRAGMENT_SHADER)
            stride = 36

            # Lines VAO
            if self.num_lines > 0:
                self.vao_lines = glGenVertexArrays(1)
                glBindVertexArray(self.vao_lines)
                self.vbo_lines = self._create_vbo(self.lines_buffer)
                glEnableVertexAttribArray(0); glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
                glEnableVertexAttribArray(1); glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
                glEnableVertexAttribArray(2); glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(28))
                glEnableVertexAttribArray(3); glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(32))

            # Points VAO
            self.vao_points = glGenVertexArrays(1)
            glBindVertexArray(self.vao_points)
            self.vbo_points = self._create_vbo(self.points_buffer)
            glEnableVertexAttribArray(0); glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
            glEnableVertexAttribArray(1); glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2); glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(28))
            glEnableVertexAttribArray(3); glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(32))

            # Uniform locations
            self.u_mvp = glGetUniformLocation(self.program, b"u_mvp")
            self.u_time = glGetUniformLocation(self.program, b"u_time")
            self.u_breathing = glGetUniformLocation(self.program, b"u_breathing")
            self.u_state = glGetUniformLocation(self.program, b"u_state")
            self.u_scanline_pos = glGetUniformLocation(self.program, b"u_scanline_pos")
            self.u_vocal_energy = glGetUniformLocation(self.program, b"u_vocal_energy")
            self.u_is_point = glGetUniformLocation(self.program, b"u_is_point")

            glBindVertexArray(0)
            self._gl_ready = True
            print("[GL] Celestial Goddess Hologram Initialized Successfully.")
        except Exception:
            import traceback
            traceback.print_exc()
            self._gl_ready = False

    def _create_vbo(self, data):
        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
        return vbo

    def _compile_shader_program(self, v_src, f_src):
        vs = glCreateShader(GL_VERTEX_SHADER)
        glShaderSource(vs, [v_src.encode()])
        glCompileShader(vs)
        if not glGetShaderiv(vs, GL_COMPILE_STATUS):
            print("[GL] Vertex error:", glGetShaderInfoLog(vs).decode())

        fs = glCreateShader(GL_FRAGMENT_SHADER)
        glShaderSource(fs, [f_src.encode()])
        glCompileShader(fs)
        if not glGetShaderiv(fs, GL_COMPILE_STATUS):
            print("[GL] Fragment error:", glGetShaderInfoLog(fs).decode())

        prog = glCreateProgram()
        glAttachShader(prog, vs)
        glAttachShader(prog, fs)
        glLinkProgram(prog)
        if not glGetProgramiv(prog, GL_LINK_STATUS):
            print("[GL] Link error:", glGetProgramInfoLog(prog).decode())
        glDeleteShader(vs)
        glDeleteShader(fs)
        return prog

    def update_frame(self):
        self.time += 0.016

        # Smooth camera damping
        self.rot_x += (self.target_rot_x - self.rot_x) * 0.12
        self.rot_y += (self.target_rot_y - self.rot_y) * 0.12
        self.zoom += (self.target_zoom - self.zoom) * 0.15

        # Move subtle vertical holographic laser scanline
        self.scanline_y -= 1.8
        if self.scanline_y < -90.0:
            self.scanline_y = 100.0

        # Modulate vocal energy smoothly
        self.vocal_energy += (self.target_vocal_energy - self.vocal_energy) * 0.20
        self.update()

    def set_state(self, state: str):
        self.state = state
        if state == "speaking":
            self.target_vocal_energy = 1.0
        else:
            self.target_vocal_energy = 0.0

    def _state_to_int(self) -> int:
        if self.state == "listening":
            return 1
        if self.state in ("understanding", "planning", "processing", "executing"):
            return 2
        if self.state == "speaking":
            return 3
        if self.state == "waiting_confirmation":
            return 4
        return 0

    def paintGL(self):
        if not self._gl_ready:
            return

        glClear(GL_COLOR_BUFFER_BIT)
        glUseProgram(self.program)

        w = max(self.width(), 1)
        h = max(self.height(), 1)
        aspect = w / h

        # Gentle organic yaw drift when idle
        organic_yaw = math.sin(self.time * 0.35) * 0.025
        if self.state in ("understanding", "planning"):
            organic_yaw = math.sin(self.time * 1.5) * 0.06

        total_yaw = self.rot_y + organic_yaw
        total_pitch = self.rot_x

        cos_y, sin_y = math.cos(total_yaw), math.sin(total_yaw)
        cos_p, sin_p = math.cos(total_pitch), math.sin(total_pitch)

        fov = 38.0
        near, far = 10.0, 2500.0
        f_val = 1.0 / math.tan(math.radians(fov) / 2.0)
        proj = np.zeros((4, 4), dtype=np.float32)
        proj[0, 0] = f_val / aspect
        proj[1, 1] = f_val
        proj[2, 2] = -(far + near) / (far - near)
        proj[3, 2] = -1.0
        proj[2, 3] = -(2.0 * far * near) / (far - near)

        r_yaw = np.eye(4, dtype=np.float32)
        r_yaw[0, 0] = cos_y;  r_yaw[0, 2] = sin_y
        r_yaw[2, 0] = -sin_y; r_yaw[2, 2] = cos_y

        r_pitch = np.eye(4, dtype=np.float32)
        r_pitch[1, 1] = cos_p;  r_pitch[1, 2] = -sin_p
        r_pitch[2, 1] = sin_p;  r_pitch[2, 2] = cos_p

        rot = np.matmul(r_pitch, r_yaw)

        model = np.eye(4, dtype=np.float32)
        model[:3, :3] = rot[:3, :3]
        model[1, 3] = -24.0 # Portrait centering: head and chest fill view
        model[2, 3] = self.zoom

        mvp = np.matmul(proj, model)

        breath_amp = 0.5
        if self.state == "speaking":
            breath_amp = 1.6
        elif self.state == "listening":
            breath_amp = 0.9

        glUniformMatrix4fv(self.u_mvp, 1, GL_FALSE, mvp.T)
        glUniform1f(self.u_time, self.time)
        glUniform1f(self.u_breathing, breath_amp)
        glUniform1i(self.u_state, self._state_to_int())
        glUniform1f(self.u_scanline_pos, self.scanline_y)
        glUniform1f(self.u_vocal_energy, self.vocal_energy)

        # Pass 1: Constellation filament lines
        if self.num_lines > 0:
            glUniform1i(self.u_is_point, 0)
            glLineWidth(1.0)
            glBindVertexArray(self.vao_lines)
            glDrawArrays(GL_LINES, 0, self.num_lines)

        # Pass 2: Celestial Stardust Particles & Radiant Stars
        glUniform1i(self.u_is_point, 1)
        glBindVertexArray(self.vao_points)
        glDrawArrays(GL_POINTS, 0, self.num_points)

        glBindVertexArray(0)

    # ---------------------------------------------------------
    # Interactive 3D Orbit Mouse Controls
    # ---------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._drag_start = event.pos()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start is not None:
            delta = event.pos() - self._drag_start
            self._drag_start = event.pos()

            if event.buttons() & Qt.LeftButton:
                self.target_rot_y += delta.x() * 0.008
                self.target_rot_x += delta.y() * 0.008
                self.target_rot_x = max(-0.7, min(0.7, self.target_rot_x))
            elif event.buttons() & Qt.RightButton:
                self.target_zoom += delta.y() * 1.2
                self.target_zoom = max(-450.0, min(-140.0, self.target_zoom))
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # Reset camera view to front portrait
        self.target_rot_x = 0.0
        self.target_rot_y = 0.0
        self.target_zoom = -230.0
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        self.target_zoom += delta * 0.4
        self.target_zoom = max(-450.0, min(-140.0, self.target_zoom))
        event.accept()


# -------------------------------------------------------------
# Transparent HUD Overlay
# -------------------------------------------------------------
class HudOverlay(QWidget):
    def __init__(self, parent, target_gl):
        super().__init__(parent)
        self.target_gl = target_gl
        self.setObjectName("hudOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("#hudOverlay { background: transparent; }")

    def mousePressEvent(self, event: QMouseEvent):
        self.target_gl.mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        self.target_gl.mouseMoveEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.target_gl.mouseReleaseEvent(event)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.target_gl.mouseDoubleClickEvent(event)
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        self.target_gl.wheelEvent(event)
        event.accept()


# -------------------------------------------------------------
# Main HUD Desktop Window
# -------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, manager=None):
        super().__init__()
        self.manager = manager
        self._drag_pos = None

        self.setWindowTitle("JARVIS — Celestial Hologram")
        self.resize(720, 880)
        self.setMinimumSize(600, 720)

        # Frameless dark cosmic window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("QMainWindow { background-color: #00040c; }")

        container = QWidget(self)
        container.setObjectName("centralContainer")
        container.setStyleSheet("#centralContainer { background: transparent; }")
        self.setCentralWidget(container)
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Central 3D Hologram
        self.humanoid = CelestialGoddessGL()
        main_layout.addWidget(self.humanoid)

        # Floating Transparent HUD Overlay
        self.overlay = HudOverlay(container, self.humanoid)
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(22, 18, 22, 18)

        # Top Bar: Status Chip & Close Button
        top_bar = QHBoxLayout()
        self.status_chip = QLabel("JARVIS // CELESTIAL CONSCIOUSNESS // FULL_CONTROL")
        self.status_chip.setStyleSheet("""
            QLabel {
                color: rgba(60, 200, 255, 0.95);
                font-family: 'Consolas', 'Segoe UI', monospace;
                font-size: 11px;
                letter-spacing: 2px;
                font-weight: bold;
                background: rgba(4, 16, 36, 0.75);
                padding: 6px 14px;
                border-radius: 4px;
                border: 1px solid rgba(0, 210, 255, 0.35);
            }
        """)
        top_bar.addWidget(self.status_chip)
        top_bar.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(6, 18, 36, 0.75);
                color: rgba(60, 200, 255, 0.85);
                border: 1px solid rgba(0, 210, 255, 0.35);
                border-radius: 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 60, 80, 0.85);
                color: white;
                border-color: rgba(255, 60, 80, 1.0);
            }
        """)
        close_btn.clicked.connect(self.close)
        top_bar.addWidget(close_btn)
        overlay_layout.addLayout(top_bar)

        overlay_layout.addStretch()

        # Dynamic Speech Subtitle Box
        self.msg_lbl = QLabel("")
        self.msg_lbl.setStyleSheet("""
            QLabel {
                color: rgba(240, 250, 255, 0.98);
                font-family: 'Segoe UI', 'Consolas', sans-serif;
                font-size: 14px;
                line-height: 1.4;
                background: rgba(3, 14, 32, 0.88);
                padding: 12px 20px;
                border-radius: 8px;
                border: 1px solid rgba(0, 210, 255, 0.4);
            }
        """)
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setAlignment(Qt.AlignCenter)
        self.msg_lbl.hide()
        overlay_layout.addWidget(self.msg_lbl)

        # Message auto-hide timer
        self.msg_timer = QTimer(self)
        self.msg_timer.setSingleShot(True)
        self.msg_timer.timeout.connect(self.clear_message)

        # Audio Spectrum Visualizer Bar
        self.audio_bar = QProgressBar()
        self.audio_bar.setFixedHeight(3)
        self.audio_bar.setTextVisible(False)
        self.audio_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(0, 20, 45, 0.5);
                border: none;
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 200, 255, 0.3),
                    stop:0.5 rgba(130, 220, 255, 0.95),
                    stop:1 rgba(0, 200, 255, 0.3));
                border-radius: 1px;
            }
        """)
        self.audio_bar.setValue(60)
        overlay_layout.addWidget(self.audio_bar)

        # Command Input Bar
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("SPEAK OR TYPE TO JARVIS...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background: rgba(3, 16, 36, 0.85);
                border: 1px solid rgba(0, 210, 255, 0.38);
                border-radius: 6px;
                color: rgba(210, 245, 255, 0.98);
                font-size: 12px;
                letter-spacing: 2px;
                font-family: 'Consolas', 'Segoe UI', monospace;
                padding: 10px 18px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(0, 245, 255, 0.95);
                background: rgba(4, 22, 48, 0.95);
            }
        """)
        self.input_field.setAlignment(Qt.AlignCenter)
        self.input_field.returnPressed.connect(self.submit_text)
        overlay_layout.addWidget(self.input_field)

        # Connect to Event Hub
        if self.manager:
            self.evt_thread = EventListenerThread(self.manager)
            self.evt_thread.event_received.connect(self.handle_event)
            self.evt_thread.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(0, 0, self.width(), self.height())

    def submit_text(self):
        text = self.input_field.text().strip()
        if text and self.manager:
            if self.manager.state == "waiting_confirmation":
                self.manager.submit_text(
                    "yes" if text.lower() in ("yes", "y", "confirm", "ok", "proceed") else "no"
                )
            else:
                self.manager.submit_text(text)
            self.input_field.clear()

    @Slot(object)
    def handle_event(self, evt):
        if isinstance(evt, str):
            try:
                evt = json.loads(evt)
            except Exception:
                return
        if not isinstance(evt, dict):
            return

        evt_type = evt.get("type")
        if evt_type == "state":
            state = evt.get("state", "idle")
            self.humanoid.set_state(state)
            self.status_chip.setText(f"JARVIS // {state.upper()} // FULL_CONTROL")
            if state == "waiting_confirmation":
                self.show_message("Waiting for confirmation (Yes / No)...")
        elif evt_type == "message":
            if evt.get("role") == "assistant":
                text = evt.get("text", "")
                if text:
                    self.show_message(text)

    def show_message(self, text):
        self.msg_lbl.setText(text)
        self.msg_lbl.show()
        self.msg_timer.start(9000)

    def clear_message(self):
        self.msg_lbl.hide()
        self.msg_lbl.setText("")

    # Drag window by top area
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and event.pos().y() < 60:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        event.accept()

    def closeEvent(self, event):
        if getattr(self, "manager", None):
            self.evt_thread.stop()
            self.manager.stop()
        super().closeEvent(event)


def start_desktop_ui(manager=None):
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.AA_UseDesktopOpenGL, True)
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()
    window = MainWindow(manager)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    start_desktop_ui()
