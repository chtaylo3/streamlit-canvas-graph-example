import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { waitForGalleryStable } from "./harness";

async function useManifestCollections(page: import("@playwright/test").Page) {
  await page.getByText("Canvas display", { exact: true }).click();
  await page.getByRole("radiogroup", { name: "Manifest children", exact: true })
    .getByRole("radio", { name: "Always collection", exact: true }).press("Space");
  await waitForGalleryStable(page);
  await page.getByText("Canvas display", { exact: true }).click();
  await waitForGalleryStable(page);
}

test("real app preserves categories through emphasis, expansion, and display changes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator('[data-testid="stMetric"]')).toHaveCount(4, { timeout: 30_000 });
  await waitForGalleryStable(page);
  await page.getByRole("button", { name: "Explore dependency groups", exact: true }).click();
  // The fixture has 8 direct and 9 resolved children, both below cutoff 12.
  // Verify the default tree view before opting into collection behavior.
  await expect(page.locator(".sgc-group-marker")).toHaveCount(0);
  await expect(page.locator(".sgc-node")).toHaveCount(20);
  await useManifestCollections(page);
  const direct = page.locator('.sgc-group-marker[data-sgc-group="depends_on"]').first();
  const resolved = page.locator('.sgc-group-marker[data-sgc-group="resolves"]').first();
  await expect(direct).toHaveText("8", { timeout: 20_000 });
  await expect(resolved).toHaveText("9");
  await expect(page.locator(".sgc-node")).toHaveCount(3);
  const accessibility = await new AxeBuilder({ page }).withRules(["nested-interactive"]).analyze();
  expect(accessibility.violations.filter((v) => v.nodes.some((n) => JSON.stringify(n.target).includes("sgc-")))).toEqual([]);
  await direct.click();
  await expect(direct).toHaveAttribute("aria-expanded", "true");
  await expect(resolved).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".sgc-node")).toHaveCount(11);
  await expect(page.getByRole("button", { name: "dependency depends_on-0, Direct", exact: true })).toBeVisible();
  await expect.poll(() => page.locator(".react-flow__edge-path[marker-end]").count()).toBeGreaterThan(0);
  await waitForGalleryStable(page);
  // Internal collection edges use ELK sections. Ancestor and collection-boundary
  // connectors can legitimately use the smooth-step fallback.
  const memberIds = await page.locator('.react-flow__node').evaluateAll(nodes => nodes
    .filter(n => n.querySelector('.sgc-node-type')?.textContent === 'dependency')
    .map(n => n.getAttribute('data-id')));
  const geometry = await page.locator('.react-flow__edge').evaluateAll((edges, ids) => edges
    .filter(edge => {
      const id = edge.getAttribute('data-id') ?? '';
      if (!id.startsWith('edge-')) return false;
      const [source, target] = JSON.parse(id.slice(5));
      return ids.includes(source) && ids.includes(target);
    })
    .map(edge => edge.querySelector('.react-flow__edge-path')?.getAttribute('d')), memberIds);
  expect(geometry).toHaveLength(8);
  expect(geometry.every((d) => d && !/[CQ]/.test(d))).toBe(true);
  await direct.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".sgc-node")).toHaveCount(3);
  await resolved.click();
  await expect(page.locator(".sgc-node")).toHaveCount(12);
  await resolved.click();
  await expect(page.locator(".sgc-node")).toHaveCount(3);

  await page.getByText("Canvas display", { exact: true }).click();
  const mode = page.getByRole("radiogroup", { name: "Manifest children", exact: true });
  await mode.getByRole("radio", { name: "Always tree", exact: true }).press("Space");
  await expect(page.locator(".sgc-group-marker")).toHaveCount(0);
  await expect(page.locator(".sgc-node")).toHaveCount(20);
  await mode.getByRole("radio", { name: "Use cutoff", exact: true }).press("Space");
  const cutoff = page.getByRole("spinbutton", { name: "Manifest cutoff", exact: true });
  await cutoff.fill("9");
  await cutoff.press("Enter");
  await expect(page.locator('.sgc-group-marker[data-sgc-group="depends_on"]')).toHaveCount(0);
  await expect(resolved).toHaveText("9");
  await expect(page.locator(".sgc-node")).toHaveCount(11);
  await mode.getByRole("radio", { name: "Always collection", exact: true }).press("Space");
  await expect(direct).toHaveText("8");
  await expect(page.locator(".sgc-node")).toHaveCount(3);

  // Borders retain a real screen-pixel width under the outer CSS zoom transform.
  const zoomOut = page.locator(".react-flow__controls-zoomout");
  for (let i = 0; i < 20 && await zoomOut.isEnabled(); i++) await zoomOut.click();
  await expect(zoomOut).toBeDisabled();
  await expect.poll(() => page.locator(".sgc-node-outline rect").first().evaluate((rect) => {
    const matrix = (rect as SVGRectElement).getScreenCTM()!;
    return Number((parseFloat(getComputedStyle(rect).strokeWidth) * Math.hypot(matrix.a, matrix.b)).toFixed(2));
  })).toBe(1.5);
  await page.screenshot({ path: "test-results/low-zoom.png" });
  expect(errors).toEqual([]);
  await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
});

test("peer exploration uses eager component groups and retains optional peers", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[data-testid="stMetric"]')).toHaveCount(4, { timeout: 30_000 });
  await waitForGalleryStable(page);
  await page.getByRole("button", { name: "Explore dependency groups", exact: true }).click();
  await useManifestCollections(page);
  const direct = page.locator('.sgc-group-marker[data-sgc-group="depends_on"]').first();
  await expect(direct).toHaveText("8", { timeout: 20_000 });
  await direct.click();
  await page.getByRole("button", { name: "dependency depends_on-0, Direct", exact: true }).click();
  await expect(page.getByRole("heading", { name: "depends_on-0", exact: true })).toBeVisible({ timeout: 20_000 });
  await waitForGalleryStable(page);
  await expect(page.getByText("Direct dependency of uv.lock.", { exact: true })).toBeVisible();
  await expect(page.getByText("Also required through other dependencies.", { exact: true })).toBeVisible();
  await page.getByText("Canvas display", { exact: true }).click();
  const mode = page.getByRole("radiogroup", { name: "Dependency children", exact: true });
  await mode.getByRole("radio", { name: "Always collection", exact: true }).press("Space");
  const peers = page.locator('.sgc-group-marker[data-sgc-group="peer_requires"]');
  await expect(peers).toHaveText("2");
  await peers.click();
  await expect(peers).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: "dependency peer-host", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "dependency depends_on-1, Direct", exact: true })).toBeVisible();
  await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
});

test("sibling repository context has configurable opacity and remains selectable", async ({ page }) => {
  page.setDefaultTimeout(15_000);
  await page.goto("/");
  await expect(page.locator('[data-testid="stMetric"]')).toHaveCount(4, { timeout: 30_000 });
  await page.getByRole("button", { name: "Explore dependency groups", exact: true }).click();
  await waitForGalleryStable(page);
  await page.getByRole("button", { name: /^repository payments-api,/ }).click();
  await expect(page.getByRole("heading", { name: "payments-api", exact: true })).toBeVisible();
  await waitForGalleryStable(page);
  const manifests = page.locator('.sgc-node-type').filter({ hasText: /^manifest$/ });
  const manifestCount = await manifests.count();
  await page.getByText("Canvas display", { exact: true }).click();
  await page.getByLabel("Show siblings", { exact: true }).press("Space");
  const faded = page.locator('.sgc-node-container').filter({ has: page.locator('.sgc-node-type', { hasText: /^repository$/ }) });
  await expect.poll(async () => faded.evaluateAll(nodes => nodes.filter(n => getComputedStyle(n).opacity === "0.2").length)).toBeGreaterThan(0);
  await expect(manifests).toHaveCount(manifestCount);
  const slider = page.getByRole("slider", { name: /Opacity/ });
  await slider.focus();
  await slider.press("End");
  await expect.poll(async () => faded.evaluateAll(nodes => nodes.filter(n => getComputedStyle(n).opacity === "0.8").length)).toBeGreaterThan(0);
  const sibling = page.locator('.sgc-node-container[style*="opacity: 0.8"]').first();
  const name = await sibling.locator('strong').innerText();
  await waitForGalleryStable(page);
  const viewport = await page.locator('.react-flow__viewport').getAttribute('style');
  const peerOrder = () => faded.evaluateAll(nodes => nodes.sort((a,b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x).map(n => n.querySelector('strong')!.textContent));
  const orderBefore = await peerOrder();
  const contextGeometry = async () => ({
    nodes: await page.locator('.react-flow__node').evaluateAll(nodes=>Object.fromEntries(nodes
      .filter(n=>/^(repository|account)$/.test(n.querySelector('.sgc-node-type')?.textContent??''))
      .map(n=>[(n as HTMLElement).dataset.id,(n as HTMLElement).style.transform]))),
    edges: await page.locator('.react-flow__edge').evaluateAll(edges=>Object.fromEntries(edges
      .map(e=>[e.getAttribute('data-id'),e.querySelector('.react-flow__edge-path')?.getAttribute('d')])))
  });
  const geometryBefore=await contextGeometry();
  expect(Object.keys(geometryBefore.nodes).length).toBeGreaterThan(2);
  expect(Object.keys(geometryBefore.edges).length).toBeGreaterThan(1);
  await sibling.getByRole("button").click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible({ timeout: 30_000 });
  await waitForGalleryStable(page);
  await expect.poll(peerOrder).toEqual(orderBefore);
  const geometryAfter=await contextGeometry();
  expect(geometryAfter.nodes).toEqual(geometryBefore.nodes);
  for (const [id,path] of Object.entries(geometryBefore.edges)) {
    if (id in geometryAfter.edges) expect(geometryAfter.edges[id]).toEqual(path);
  }
  await expect(page.locator('.react-flow__viewport')).toHaveAttribute('style', viewport!);
  await page.getByLabel("Show siblings", { exact: true }).press("Space");
  await expect(page.locator('.sgc-node-container[style*="opacity"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
});

async function recordMotion(page: import("@playwright/test").Page) {
  await page.locator('[data-sgc-status="ready"]').evaluate((host) => {
    const state = { frames: [] as Array<{ transforms: string[]; fading: boolean }>, viewport: host.querySelector('.react-flow__viewport') };
    (window as any).__motionProbe = state;
    const tick = () => {
      if (!host.isConnected || (window as any).__motionProbe !== state) return;
      if (host.getAttribute('data-sgc-transition') === 'running' && state.frames.length < 2000) {
        const nodes = [...host.querySelectorAll<HTMLElement>('.react-flow__node')];
        state.frames.push({ transforms: nodes.map(n => n.style.transform), fading: nodes.some(n => Number(n.style.opacity) > 0 && Number(n.style.opacity) < 1) });
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

test("hierarchy navigation animates a persistent canvas and interrupted groups settle", async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.locator('[data-testid="stMetric"]')).toHaveCount(4, {timeout:30_000});
  await waitForGalleryStable(page);
  await useManifestCollections(page);
  await recordMotion(page);
  await page.getByRole('button', {name:/^repository payments-api,/}).click();
  await expect(page.getByRole('heading', {name:'payments-api', exact:true})).toBeVisible();
  await waitForGalleryStable(page);
  await page.getByRole('button', {name:'manifest uv.lock', exact:true}).click();
  await expect(page.getByRole('heading', {name:'uv.lock', exact:true})).toBeVisible();
  await waitForGalleryStable(page);
  const direct = page.locator('.sgc-group-marker[data-sgc-group="depends_on"]').first();
  await direct.press('Enter');
  await expect(page.locator('[data-sgc-transition="running"]')).toHaveCount(1);
  await direct.press('Enter');
  await waitForGalleryStable(page);
  await expect(direct).toHaveAttribute('aria-expanded','false');
  await expect(page.locator('.react-flow__node[inert]')).toHaveCount(0);
  await page.getByRole('button', {name:/^repository payments-api,/}).click();
  await expect(page.getByRole('heading', {name:'payments-api', exact:true})).toBeVisible();
  await waitForGalleryStable(page);
  const result = await page.locator('[data-sgc-status="ready"]').evaluate(host => {
    const probe=(window as any).__motionProbe;
    return { persistent:probe.viewport===host.querySelector('.react-flow__viewport'), count:probe.frames.length,
      faded:probe.frames.some((f:any)=>f.fading), changed:new Set(probe.frames.map((f:any)=>JSON.stringify(f.transforms))).size };
  });
  expect(result.persistent, JSON.stringify(result)).toBe(true);
  expect(result.count).toBeGreaterThan(2);
  expect(result.faded, JSON.stringify(result)).toBe(true);
  expect(result.changed).toBeGreaterThan(2);
  expect(errors).toEqual([]);
  await expect(page.locator('[data-testid="stException"]')).toHaveCount(0);
});

test("reduced motion skips navigation animation", async ({ page }) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/');
  await expect(page.locator('[data-testid="stMetric"]')).toHaveCount(4, {timeout:30_000});
  await waitForGalleryStable(page);
  await recordMotion(page);
  await page.getByRole('button', {name:'Explore dependency groups', exact:true}).click();
  await expect(page.getByRole('heading', {name:'uv.lock', exact:true})).toBeVisible();
  await waitForGalleryStable(page);
  await expect(page.locator('[data-sgc-transition-duration="0"]')).toHaveCount(1);
  expect(await page.evaluate(()=>(window as any).__motionProbe.frames.length)).toBe(0);
  await expect(page.locator('.react-flow__node[inert]')).toHaveCount(0);
});
