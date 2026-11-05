# EJC Climate Frontline: digital strand

Prototype work for the Climate Frontline no-cost extension (EJC / Plus, with Code for Africa).

## Valencia Flood Protection Register (seed prototype)

A static, single-page register of commitments made to reduce future flood risk after the October 2024 DANA in Valencia. Each record shows its evidence chain (promised, funded, contracted, under way, completed, benefit assessed), what is known, what is not yet established, and the next evidence request. It is adapted from the Climate Protection Register prototype for Bologna and Barcelona.

**Status:** seed records for team review. They have not yet been re-verified by an editor. The page carries `noindex, nofollow`, but anyone with the link can open it.

## Structure

- `site/index.html`: the register (HTML, CSS, JS and seed data in one file; no build step)
- `.github/workflows/pages.yml`: deploys `site/` to GitHub Pages on every push to `main` that touches `site/`

## Deploy

In **Settings → Pages**, set **Source** to **GitHub Actions**. Pushes to `main` then deploy automatically. The site lives at `https://codeforafrica.github.io/ejc-climate-frontline/`.

## Next steps

- Move seed records out of `index.html` into `data/records.csv` with a written data contract.
- Add ingestion scripts for official sources (CHJ, GVA Oberta, Diputació portal, PLACSP, BOE).
- Editorial review of every record before any public launch.
