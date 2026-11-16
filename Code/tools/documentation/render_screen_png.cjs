/** @file @brief 로컬 SVG를 headless 브라우저로 렌더링하고 글자 잘림을 확인한다. */
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

/** @brief 지정한 Playwright 설치를 이용하며 제품 의존성을 추가하지 않는다. */
async function main()
{
    const [moduleRoot, browserPath] = process.argv.slice(2);
    if (!moduleRoot || !browserPath)
    {
        throw new Error('사용법: node render_screen_png.cjs <node_modules> <브라우저 실행 파일>');
    }
    const { chromium } = require(path.join(moduleRoot, 'playwright'));
    const folder = path.resolve(__dirname, '../../../01_개발문서/04_화면설계/01_그림자료');
    const browser = await chromium.launch({executablePath: browserPath, headless: true});
    const report = [];
    try
    {
        const page = await browser.newPage({viewport: {width: 1600, height: 1000}, deviceScaleFactor: 1});
        for (const file of fs.readdirSync(folder).filter(name => name.endsWith('.svg')).sort())
        {
            await page.goto(pathToFileURL(path.join(folder, file)).href);
            await page.evaluate(() => document.fonts.ready);
            const overflow = await page.evaluate(() =>
            {
                const failures = [];
                for (const text of document.querySelectorAll('svg > text'))
                {
                    const box = text.getBBox();
                    let owner = text.previousElementSibling;
                    while (owner && !['rect', 'ellipse'].includes(owner.tagName))
                    {
                        owner = owner.previousElementSibling;
                    }
                    if (owner)
                    {
                        const bounds = owner.getBBox();
                        if (box.x < bounds.x || box.y < bounds.y || box.x + box.width > bounds.x + bounds.width || box.y + box.height > bounds.y + bounds.height)
                        {
                            failures.push(text.textContent);
                        }
                    }
                }
                return failures;
            });
            await page.locator('svg').screenshot({path: path.join(folder, file.replace(/\.svg$/, '.png'))});
            report.push({file, overflow});
        }
    }
    finally
    {
        await browser.close();
    }
    console.log(JSON.stringify(report, null, 2));
    if (report.some(item => item.overflow.length))
    {
        process.exitCode = 1;
    }
}

main().catch(error =>
{
    console.error(error.message);
    process.exitCode = 1;
});
