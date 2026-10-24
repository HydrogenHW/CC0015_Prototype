/**
 * 点图标 → 确认本地服务活着 → 打开或聚焦字幕页。
 *
 * 为什么先探测再打开：服务没跑时直接开标签页，用户看到的只是一个
 * 「无法访问此网站」的浏览器错误页，根本不知道问题出在服务没启动。
 * 先探测一次，能给出一句人话。
 */
const APP_URL = "http://127.0.0.1:8000/";
const HEALTH_URL = "http://127.0.0.1:8000/health";

async function serviceAlive() {
  try {
    const res = await fetch(HEALTH_URL, {
      cache: "no-store",
      signal: AbortSignal.timeout(1500),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return data && data.ok === true;
  } catch {
    return false;
  }
}

async function openOrFocus() {
  const existing = await chrome.tabs.query({ url: APP_URL + "*" });
  if (existing.length > 0) {
    const tab = existing[0];
    await chrome.tabs.update(tab.id, { active: true });
    if (tab.windowId != null) {
      await chrome.windows.update(tab.windowId, { focused: true });
    }
    return;
  }
  await chrome.tabs.create({ url: APP_URL });
}

chrome.action.onClicked.addListener(async () => {
  const alive = await serviceAlive();
  if (alive) {
    await openOrFocus();
  } else {
    await chrome.tabs.create({ url: chrome.runtime.getURL("offline.html") });
  }
});
