import logging
from typing import List, Tuple

from media_modules._utils import UA, get_requests_cookies, download_url

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

log = logging.getLogger("downloader.instagram.playwright")

def playwright_instagram(url: str) -> Tuple[List[str], str]:
    if not PLAYWRIGHT_AVAILABLE:
        return [], ""

    files: List[str] = []
    title = "Instagram Media"
    try:
        with sync_playwright() as p:
            launch_args = {'headless': True, 'args': ['--disable-blink-features=Automation', '--no-sandbox']}
            browser = None
            for channel in ('chrome', 'msedge', 'chromium'):
                try:
                    browser = p.chromium.launch(channel=channel, **launch_args)
                    break
                except Exception:
                    continue
            if not browser:
                return [], ""

            context = None
            try:
                context = browser.new_context(viewport={'width': 1280, 'height': 1200}, user_agent=UA)
                page = context.new_page()
                clean_url = url.split('?')[0]
                page.goto(clean_url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(4000)
                try:
                    title = page.title().split(' • ')[0][:100]
                except Exception:
                    pass

                media_urls = []
                for img in page.query_selector_all('img[src*="cdninstagram"]'):
                    src = img.get_attribute('src')
                    if src:
                        media_urls.append(src)
                for vid in page.query_selector_all('video[src*="cdninstagram"]'):
                    src = vid.get_attribute('src')
                    if src:
                        media_urls.append(src)

                seen = set()
                cookies = get_requests_cookies()
                for mu in list(dict.fromkeys(media_urls)):
                    mu_clean = mu.split('&_nc_cat')[0]
                    if mu_clean in seen:
                        continue
                    seen.add(mu_clean)
                    f = download_url(mu, "ig_pw", cookies=cookies, referer="https://www.instagram.com/")
                    if f:
                        files.append(f)
                    if len(files) >= 10:
                        break
            finally:
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        log.debug("playwright instagram failed: %s", e)
    return files, title
