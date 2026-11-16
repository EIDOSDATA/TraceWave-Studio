/** @file @brief 구현 시안을 Windows 글꼴로 렌더링하고 텍스트와 캔버스 경계를 검사한다. */
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const crypto = require('node:crypto');

/** @brief 제품 GUI와 분리된 정적 SVG를 실제 브라우저 글꼴 엔진으로 검수한다. */
async function main()
{
    const [moduleRoot, browserPath, folder, reportPath] = process.argv.slice(2);
    if (!moduleRoot || !browserPath || !folder || !reportPath)
    {
        throw new Error('사용법: node render_studio_views.cjs <node_modules> <browser> <그림폴더> <검수json>');
    }
    const {chromium} = require(path.join(moduleRoot, 'playwright'));
    const browser = await chromium.launch({executablePath: browserPath, headless: true});
    const records = [];
    try
    {
        const page = await browser.newPage({deviceScaleFactor: 1});
        for (const name of fs.readdirSync(folder).filter(name => name.endsWith('.svg')).sort())
        {
            const svgPath = path.resolve(folder, name);
            await page.goto(pathToFileURL(svgPath).href);
            await page.evaluate(() => document.fonts.ready);
            const result = await page.evaluate(() =>
            {
                const svg = document.querySelector('svg');
                const width = Number(svg.getAttribute('width'));
                const height = Number(svg.getAttribute('height'));
                const failures = [];
                for (const node of svg.querySelectorAll('text'))
                {
                    const box = node.getBBox();
                    const limit = Number(node.getAttribute('data-max-width'));
                    if (limit > 0 && box.width > limit + 0.75)
                    {
                        failures.push({type: 'text_width', text: node.textContent, width: box.width, limit, x: box.x, y: box.y});
                    }
                    if (box.x < -0.75 || box.y < -0.75 || box.x + box.width > width + 0.75 || box.y + box.height > height + 0.75)
                    {
                        failures.push({type: 'outside_viewport', text: node.textContent, x: box.x, y: box.y});
                    }
                }
                return {width, height, failures, textCount: svg.querySelectorAll('text').length};
            });
            await page.setViewportSize({width: result.width, height: result.height});
            await page.screenshot({path: svgPath.replace(/\.svg$/, '.png'), fullPage: false});
            records.push({name, svgSha256: crypto.createHash('sha256').update(fs.readFileSync(svgPath)).digest('hex'),
                pngSha256: crypto.createHash('sha256').update(fs.readFileSync(svgPath.replace(/\.svg$/, '.png'))).digest('hex'), ...result});
        }
    }
    finally
    {
        await browser.close();
    }
    const report = {kind: 'static_visual_render_not_native_gui_test', renderer: 'headless_edge_windows', records};
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', 'utf8');
    const failures = records.reduce((sum, row) => sum + row.failures.length, 0);
    console.log(JSON.stringify({screens: records.length, textFailures: failures}));
    process.exitCode = failures ? 1 : 0;
}

main().catch(error =>
{
    console.error(error);
    process.exitCode = 1;
});
