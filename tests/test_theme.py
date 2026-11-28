"""主界面样式：只落在主窗口、对话框、托盘菜单上，图标文件齐全，按钮是中文，浮窗一个像素不变。"""
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
Q = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtGui import QColor, QImage, QPalette

from lolhex.ui import theme


@pytest.fixture
def app():
    app = Q.QApplication.instance() or Q.QApplication([])
    style, palette, sheet = app.style().objectName(), app.palette(), app.styleSheet()
    yield app
    app.setStyleSheet(sheet)
    app.setStyle(Q.QStyleFactory.create(style))
    app.setPalette(palette)
    if zh := getattr(app, "_zh", None):
        app.removeTranslator(zh)
        app._zh = None
    theme._sync_globals("light")


def test_every_rule_is_scoped_so_the_overlay_is_untouched():
    css = theme.stylesheet()
    assert "%(" not in css
    selectors = [s.strip() for block in re.findall(r"([^{}]+)\{[^{}]*\}", css) for s in block.split(",")]
    assert len(selectors) > 40
    for s in selectors:
        assert s.startswith(("QMainWindow#main", "QDialog", "QMenu#tray", "QListView#heroPopup")), s


def test_icons_exist_in_every_scale():
    for url in set(re.findall(r'url\("([^"]+)"\)', theme.stylesheet())):
        assert "\\" not in url
        for suffix in ("", "@2x", "@3x"):
            assert not QImage(url.replace(".png", f"{suffix}.png")).isNull(), url


def test_look_does_not_depend_on_the_system_style(app):
    other = next((k for k in Q.QStyleFactory.keys() if k.lower() != "fusion"), None)
    if other:
        app.setStyle(other)
    theme.apply(app)
    assert app.style().objectName().lower() == "fusion" or app.style().metaObject().className() == "QStyleSheetStyle"
    assert app.palette().color(QPalette.Highlight) == QColor(theme.ACCENT)


def test_standard_buttons_are_chinese(app):
    theme.apply(app)
    box = Q.QMessageBox(Q.QMessageBox.Question, "t", "t", Q.QMessageBox.Yes | Q.QMessageBox.No | Q.QMessageBox.Ok | Q.QMessageBox.Cancel)
    assert {b.text() for b in box.buttons()} == {"是", "否", "确定", "取消"}


def test_overlay_is_pixel_identical(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    from lolhex.config import Settings
    from lolhex.engine import Engine
    from lolhex.ui.overlay import Overlay

    def shots():
        engine = Engine(Settings.load())
        ov = Overlay(engine)
        ov.timer.stop()
        app.processEvents()
        got = [w.grab().toImage() for w in (ov.panel.btn, ov.panel.body)]
        for w in (ov.panel, ov.badges, ov.champ):
            w.deleteLater()
        engine.stop()
        return got
    app.setStyleSheet("")
    app.setStyle("Fusion")  # 同一个底子下只看样式表有没有漏到浮窗上
    before = shots()
    theme.apply(app)
    assert shots() == before
    theme.apply(app, "dark")
    assert shots() == before


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_dual_theme_stylesheet_is_scoped_and_distinct(app, mode):
    css = theme.stylesheet(mode)
    assert "%(" not in css
    selectors = [s.strip() for block in re.findall(r"([^{}]+)\{[^{}]*\}", css) for s in block.split(",")]
    assert len(selectors) > 40
    for s in selectors:
        assert s.startswith(("QMainWindow#main", "QDialog", "QMenu#tray", "QListView#heroPopup")), s
    eff = theme.apply(app, mode)
    assert eff == mode and theme.current_mode() == mode
    assert app.palette().color(QPalette.Window) == QColor(theme.THEMES[mode]["BG"])
    assert app.palette().color(QPalette.Highlight) == QColor(theme.ACCENT)
    if mode == "dark":
        # 深色模式下不能残留浅色硬编码底色
        assert "#fff7df" not in css.lower()
        assert "#f7f9fc" not in css.lower()
        assert "#f2f4f8" not in css.lower()


def test_mainwindow_live_theme_toggle_persists(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    from lolhex.config import Settings
    from lolhex.engine import Engine
    from lolhex.ui import mainwindow, overlay

    monkeypatch.setattr(mainwindow.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    s = Settings.load()
    eng = Engine(s)
    ov = overlay.Overlay(eng)
    ov.timer.stop()
    w = mainwindow.MainWindow(eng, ov)
    try:
        theme.apply(app, "light")
        w._set_theme_mode("dark")
        assert theme.current_mode() == "dark"
        assert s.theme_mode == "dark"
        assert Settings.load(tmp_path / "config.json").theme_mode == "dark"
        assert w.set_theme.currentData() == "dark"
        assert w.btn_theme.text() == "切浅色"

        w.btn_theme.click()
        assert theme.current_mode() == "light"
        assert s.theme_mode == "light"
        assert Settings.load(tmp_path / "config.json").theme_mode == "light"
        assert w.set_theme.currentData() == "light"
        assert w.btn_theme.text() == "切深色"

        # 左侧导航栏按钮与页面栈同步
        w._nav_buttons[2].click()
        assert w.tabs.currentIndex() == 2
        assert w._nav_buttons[2].property("active") is True
        assert w._nav_buttons[0].property("active") is False

        # Batch 2 新功能设置开关即时保存并生效
        w.set_shop_overlay.setChecked(False)
        w.set_enemy_rules.setChecked(False)
        w.set_teammate_ocr.setChecked(False)
        saved = Settings.load(tmp_path / "config.json")
        assert (saved.shop_overlay, saved.enemy_rules, saved.teammate_ocr) == (False, False, False)
    finally:
        w.hide()
        ov.set_visible(False)
        for widget in (w, ov.panel, ov.badges, ov.champ):
            widget.deleteLater()
        eng.stop()
        app.processEvents()
