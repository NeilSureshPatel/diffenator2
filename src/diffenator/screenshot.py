from __future__ import annotations
import selenium
from selenium import webdriver
from platform import platform
import os
from selenium.webdriver.common.by import By
from diffenator.utils import gen_gifs
import shutil
import tempfile


class ScreenShotter:
    """Use selenium to take screenshots from local browsers"""

    def __init__(self, width: int = 1280):

        self.browsers = self._get_browsers()
        self.width = width

    def _file_prefix(self, browser):
        meta = browser.capabilities
        plat = platform()
        browser = meta["browserName"]
        browser_version = meta["browserVersion"]
        return f"{plat}_{browser}_{browser_version}".replace(" ", "-")

    def take(self, url: str, dst_dir: str):
        for browser in self.browsers:
            browser.get(url)

            try:
                diff_toggle = browser.find_element(By.ID, "font-toggle")
            except selenium.common.exceptions.NoSuchElementException:
                diff_toggle = None

            if diff_toggle:
                self.take_gif(url, dst_dir)
            else:
                self.take_png(url, dst_dir)

    def take_png(self, url: str, dst_dir: str, javascript: str = "") -> list[str]:
        res = []
        for browser in self.browsers:
            file_prefix = self._file_prefix(browser)
            filename = os.path.join(dst_dir, f"{file_prefix}.png")
            browser.set_window_size(self.width, 1000)
            browser.get(url)
            if javascript:
                browser.execute_script(javascript)
            # recalc since image size since we now know the height
            body_el = browser.find_element(By.TAG_NAME, "html")
            browser.set_window_size(self.width, body_el.size["height"])
            browser.save_screenshot(filename)
            res.append(filename)
        return res

    def take_gif(self, url: str, dst_dir: str):
        before_fp = os.path.join(dst_dir, "before")
        if not os.path.exists(before_fp):
            os.mkdir(before_fp)

        after_fp = os.path.join(dst_dir, "after")
        if not os.path.exists(after_fp):
            os.mkdir(after_fp)

        self.take_png(url, before_fp)
        self.take_png(url, after_fp, javascript="switchFonts();")
        gen_gifs(before_fp, after_fp, dst_dir)

    def set_width(self, width: int):
        # we don't care about setting height since we will always return a
        # full height screenshot
        self.width = width

    def _get_browsers(self):
        """Determine which browsers we can screenshot which exist on the system"""
        # We can add more webdrivers if needed. Let's focus on these first
        supported = ["Chrome", "Firefox", "Safari"]
        has = []
        driver = webdriver
        for browser in supported:
            try:
                # TODO customise more browsers. We should aim for at least Safari and FF
                if browser == "Chrome":
                    # Using headless mode enables us to set the window size
                    # to any arbitrary value which means we can use to capture
                    # the full size of the body elem
                    options = webdriver.ChromeOptions()
                    options.add_argument("--headless")
                    options.add_argument("--hide-scrollbars")
                    options.add_argument("--force-device-scale-factor=1")
                    browser_driver = getattr(driver, browser)(options=options)
                elif browser == "Firefox":
                    options = webdriver.FirefoxOptions()
                    options.add_argument("--headless")
                    options.add_argument("--hide-scrollbars")
                    options.add_argument("--force-device-scale-factor=1")
                    browser_driver = getattr(driver, browser)(options=options)
                else:
                    browser_driver = getattr(driver, browser)()
                browser_driver.set_page_load_timeout(60)
                has.append(browser_driver)
            except:
                pass
        return has

    def __del__(self):
        for browser in self.browsers:
            browser.quit()


def screenshot_dir(dir_fp: str, out: str):
    """Screenshot a folder of html docs. Walk the damn things"""
    if not os.path.exists(out):
        os.mkdir(out)
    screenshotter = ScreenShotter()
    for dirpath, _, filenames in os.walk(dir_fp):
        for filename in filenames:
            if not filename.endswith(".html") or "diffenator" in filename:
                continue
            dir_name = os.path.join(out, filename.replace(".html", ""))
            fp = os.path.join(dirpath, filename)
            url = f"file:///{fp}"
            img_prefix_fp = (
                os.path.relpath(fp, dir_fp)
                .replace(os.path.sep, "-")
                .replace(".html", "")
            )
            with tempfile.TemporaryDirectory() as tmp:
                screenshotter.take(url, tmp)
                for f in os.listdir(tmp):
                    if not f.endswith(("png", "gif")):
                        continue
                    src = os.path.join(tmp, f)
                    dst = os.path.join(out, f"{img_prefix_fp}-{f}")
                    shutil.move(src, dst)
