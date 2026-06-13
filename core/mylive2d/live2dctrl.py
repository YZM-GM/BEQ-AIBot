import glfw
from OpenGL.GL import *
import live2d.v3 as live2d
import time
from pathlib import Path
import win32gui
from win32gui import SetWindowLong, GetWindowLong, SetLayeredWindowAttributes
from win32con import GWL_EXSTYLE, WS_EX_LAYERED, LWA_COLORKEY
import win32con

glfw.window_hint(glfw.DECORATED, glfw.FALSE)
glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)

BASE_DIR = Path(__file__).parent
MODEL_DIR = BASE_DIR / "model" / "UG"
MODEL_PATH = str(MODEL_DIR / "ugofficial.model3.json")
EXP_DIR = MODEL_DIR / "exp"
WIDTH, HEIGHT = 800, 600


def set_window_transparent(window):
    hwnd = glfw.get_win32_window(window)
    ex_style = GetWindowLong(hwnd, GWL_EXSTYLE)
    SetWindowLong(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)
    SetLayeredWindowAttributes(hwnd, 0x000000, 0, LWA_COLORKEY)
    style = GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~win32con.WS_CAPTION
    style &= ~win32con.WS_THICKFRAME
    style &= ~win32con.WS_DLGFRAME
    SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                          win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)


if not glfw.init():
    raise RuntimeError("无法初始化 GLFW")






def create_live2d():

    window = glfw.create_window(WIDTH, HEIGHT, "Live2D Viewer", None, None)
    glfw.make_context_current(window)
    glfw.swap_interval(1)
    glViewport(0, 0, WIDTH, HEIGHT)
    set_window_transparent(window)

    live2d.glInit()
    live2d.init()

    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    model = live2d.LAppModel()
    model.LoadModelJson(MODEL_PATH)
    model.Resize(WIDTH, HEIGHT)

    # ── 加载表情（均在模型根目录）────────────────────────────────────────────────
    _extra_expressions = [
        "1desk", "2mic", "3clever", "4OAO", "5QAQ",
        "6i gi a ri", "7keyboard", "8punch", "9",
    ]
    for name in _extra_expressions:
        model.LoadExtraExpression(name, str(MODEL_DIR / f"{name}.exp3.json"))

    # ── 加载循环动作 ──────────────────────────────────────────────────────────────
    model.LoadExtraMotion("idle", str(MODEL_DIR / "loop.motion3.json"))
    model.StartMotion("idle", 0, live2d.MotionPriority.NORMAL)

    print(f"加载模型: {MODEL_PATH}")
    print("可用表情:", model.GetExpressionIds())
    print("可用动作组:", model.GetMotionGroups())

    def on_resize(win, w, h):
        glViewport(0, 0, w, h)
        model.Resize(w, h)

    glfw.set_framebuffer_size_callback(window, on_resize)

    # ── 按键映射：数字键叠加切换表情，0 = 全部重置 ────────────────────────────────
    _key_expressions = {
        glfw.KEY_0: None,
        glfw.KEY_1: "1desk",
        glfw.KEY_2: "2mic",
        glfw.KEY_3: "3clever",
        glfw.KEY_4: "4OAO",
        glfw.KEY_5: "5QAQ",
        glfw.KEY_6: "6i gi a ri",
        glfw.KEY_7: "7keyboard",
        glfw.KEY_8: "8punch",
        glfw.KEY_9: "9",
    }
    _prev_keys = {k: glfw.RELEASE for k in _key_expressions}
    _active_expressions: set = set()
    try:
        while not glfw.window_should_close(window):
            glfw.poll_events()

            # 按键切换表情（再按同一键关闭，可多个叠加）
            for key, expr in _key_expressions.items():
                cur = glfw.get_key(window, key)
                if cur == glfw.PRESS and _prev_keys[key] == glfw.RELEASE:
                    if expr is None:
                        model.ResetExpressions()
                        _active_expressions.clear()
                    elif expr in _active_expressions:
                        model.RemoveExpression(expr)
                        _active_expressions.discard(expr)
                    else:
                        model.AddExpression(expr)
                        _active_expressions.add(expr)
                _prev_keys[key] = cur

            # 空格：重播循环动作
            if glfw.get_key(window, glfw.KEY_SPACE) == glfw.PRESS:
                model.StartMotion("idle", 0, live2d.MotionPriority.FORCE)

            # 鼠标控制头部朝向
            mx, my = glfw.get_cursor_pos(window)
            model.SetParameterValue("ParamAngleX",  (mx / WIDTH  - 0.5) * 60)
            model.SetParameterValue("ParamAngleY", -(my / HEIGHT - 0.5) * 60)
            model.SetParameterValue("ParamEyeBallX", (mx / WIDTH  - 0.5) * 2)
            model.SetParameterValue("ParamEyeBallY", -(my / HEIGHT - 0.5) * 2)

            glClearColor(0.0, 0.0, 0.0, 0.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            live2d.clearBuffer()
            model.Update()
            model.Draw()

            glfw.swap_buffers(window)

    except Exception:
        import traceback
        print("渲染错误:")
        traceback.print_exc()

    finally:
        model.DestroyRenderer()
        del model
        live2d.dispose()
        live2d.glRelease()
        glfw.terminate()
        print("live2D已退出")
