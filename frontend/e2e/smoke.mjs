// Navega por TODAS as telas como uma pessoa faria (computador e celular) e falha se
// aparecer erro de JavaScript ou a tela de erro. Abrir cada URL direto não basta:
// vários erros só aparecem ao TROCAR de tela, quando o React desmonta a anterior.
//
// Uso: backend rodando (com o frontend compilado e dados de exemplo), depois `npm run test:e2e`.
//   E2E_BASE_URL (padrão http://127.0.0.1:8010), E2E_USER, E2E_PASSWORD
//   E2E_CHROME_PATH: usa um Chrome/Chromium já instalado
//   E2E_SCREENSHOTS: pasta para salvar capturas de tela
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8010";
const USER = process.env.E2E_USER ?? "admin";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";
const SHOTS = process.env.E2E_SCREENSHOTS;
const launch = process.env.E2E_CHROME_PATH ? { executablePath: process.env.E2E_CHROME_PATH } : {};
const CRASH = /Esta tela encontrou um erro|Unexpected Application Error/;

if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const failures = [];
let steps = 0;

async function check(page, errors, label, shot) {
  steps += 1;
  await page.waitForTimeout(400);
  const body = await page.locator("body").innerText();
  if (CRASH.test(body)) failures.push(`${label}: tela de erro -> ${body.split("\n").slice(0, 3).join(" | ")}`);
  while (errors.length) failures.push(`${label}: erro de JavaScript -> ${errors.shift()}`);
  if (SHOTS && shot) await page.screenshot({ path: `${SHOTS}/${shot}.png`, fullPage: true });
}

async function login(page) {
  await page.goto(`${BASE}/`);
  await page.waitForSelector("form");
  await page.fill('input[autocomplete="username"]', USER);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForSelector("text=Mesa de", { timeout: 30000 });
}

async function run(viewport, prefix) {
  const browser = await chromium.launch(launch);
  const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));

  await page.goto(`${BASE}/`);
  await page.waitForSelector("form");
  await check(page, errors, `${prefix} login`, `${prefix}-00-login`);
  await login(page);
  await check(page, errors, `${prefix} console`, `${prefix}-01-console`);

  const mobile = viewport.width < 768;
  const nav = async (label) => {
    if (mobile) await page.getByRole("button", { name: "Abrir menu" }).click();
    await page.getByRole("link", { name: label }).first().click();
  };

  for (const [label, shot] of [
    ["Fila de geração", "02-fila"],
    ["Consumo e custos", "03-consumo"],
    ["Configurações", "04-ajustes"],
    ["Canais", "05-canais"],
  ]) {
    await nav(label);
    await check(page, errors, `${prefix} ${label}`, `${prefix}-${shot}`);
  }

  // canal → abas
  const card = page.locator('a[href^="/canais/"]').first();
  if (await card.count()) {
    await card.click();
    await page.waitForSelector('[role="tablist"]');
    await check(page, errors, `${prefix} canal`, `${prefix}-06-canal`);
    for (const [tab, shot] of [
      ["Skill", "07-skill"],
      ["Aprendizados", "08-aprendizados"],
      ["Configurações", "09-canal-config"],
      ["Projetos", null],
    ]) {
      await page.getByRole("tab", { name: new RegExp(tab) }).click();
      await check(page, errors, `${prefix} canal/${tab}`, shot ? `${prefix}-${shot}` : null);
    }
    // projetos → etapas (todos os projetos do canal, no máximo 2)
    const hrefs = await page.locator('a[href^="/projetos/"]').evaluateAll((els) => els.map((e) => e.getAttribute("href")));
    for (const [pi, href] of hrefs.slice(0, 2).entries()) {
      await page.locator(`a[href="${href}"]`).first().click();
      await page.waitForSelector('nav[role="tablist"]');
      const stages = ["Roteiro", "Cenas", "Visuais", "Narração", "Vídeo final", "Thumbnail", "Título/Desc.", "Exportação", "Custos", "Arquivos"];
      for (const [i, s] of stages.entries()) {
        await page.getByRole("tab", { name: new RegExp(s.replace(".", "\\.")) }).click();
        await check(page, errors, `${prefix} projeto ${href}/${s}`, `${prefix}-p${pi}-${i + 1}`);
      }
      // abre a edição da primeira cena
      await page.getByRole("tab", { name: /Cenas/ }).click();
      const row = page.locator("text=#001").first();
      if (await row.count()) {
        await row.click();
        await check(page, errors, `${prefix} cena aberta`, mobile ? null : `${prefix}-p${pi}-cena-aberta`);
      }
      await page.goBack();
      await page.waitForSelector('a[href^="/projetos/"]');
    }
  }
  await browser.close();
}

await run({ width: 1440, height: 900 }, "desktop");
await run({ width: 390, height: 844 }, "mobile");

if (failures.length) {
  console.error(`FALHOU (${failures.length}):\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log(`OK: ${steps} telas verificadas sem erros.`);
