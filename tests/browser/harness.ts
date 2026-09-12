import { expect, type Page } from "@playwright/test";

export async function waitForGalleryStable(page: Page, expectedCanvases = 1) {
  const ready = page.locator('[data-sgc-status="ready"]');
  await expect(ready).toHaveCount(expectedCanvases, { timeout: 20_000 });
  let previousSignature = "";
  let unchangedSince = Date.now();
  await expect.poll(async () => {
    if (await ready.evaluateAll(elements => elements.some(e => e.getAttribute("data-sgc-transition") === "running" || e.getAttribute("data-sgc-layout-pending") === "true"))) { unchangedSince = Date.now(); return false; }
    const signature = await ready.evaluateAll((elements) => {
      type IdentityWindow = Window & {
        __sgcElementIds?: WeakMap<Element, number>;
        __sgcNextElementId?: number;
      };
      const root = window as IdentityWindow;
      root.__sgcElementIds ??= new WeakMap();
      root.__sgcNextElementId ??= 1;
      return elements.map((element) => {
        let id = root.__sgcElementIds!.get(element);
        if (id === undefined) {
          id = root.__sgcNextElementId!++;
          root.__sgcElementIds!.set(element, id);
        }
        return `${id}:${element.getAttribute("data-sgc-render-generation") ?? "none"}`;
      }).join(",");
    });
    if (signature !== previousSignature) {
      previousSignature = signature;
      unchangedSince = Date.now();
      return false;
    }
    return Date.now() - unchangedSince >= 2_000;
  }, { timeout: 20_000 }).toBe(true);
}

