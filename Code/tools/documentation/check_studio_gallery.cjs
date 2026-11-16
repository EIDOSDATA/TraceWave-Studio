/** @file @brief 화면 둘러보기의 로컬 자료와 탐색 동작을 실제 브라우저에서 확인한다. */
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const crypto = require('node:crypto');

/** @brief 문서 탐색 실패를 성공으로 집계하지 않는다. */
function requireCheck(value, message)
{
    if (!value)
    {
        throw new Error(message);
    }
}

/** @brief 필터, 확대, 키보드, 모든 로컬 이미지를 검수하고 기록한다. */
async function main()
{
    const [moduleRoot, browserPath, gallery, output] = process.argv.slice(2);
    requireCheck(moduleRoot && browserPath && gallery && output,
        '사용법: node check_studio_gallery.cjs <node_modules> <browser> <둘러보기HTML> <검수JSON>');
    const {chromium} = require(path.join(moduleRoot, 'playwright'));
    const browser = await chromium.launch({executablePath: browserPath, headless: true});
    try
    {
        const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
        const errors = [];
        const missing = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('response', response =>
        {
            if (response.status() >= 400)
            {
                missing.push(response.url());
            }
        });
        await page.goto(pathToFileURL(path.resolve(gallery)).href);
        requireCheck(await page.locator('article').count() === 84, '화면 수 불일치');
        await page.locator('input').fill('급전');
        requireCheck(await page.locator('article:visible').count() >= 2, '검색 실패');
        await page.locator('input').fill('');
        await page.getByRole('button', {name: '결과', exact: true}).click();
        requireCheck(await page.locator('article:visible').count() >= 8, '작업 필터 실패');
        await page.locator('article:visible .preview').first().click();
        await page.locator('#largeImage').evaluate(image => image.decode());
        requireCheck(await page.locator('#viewerDialog').evaluate(dialog => dialog.open), '확대 실패');
        const first = await page.locator('#viewerTitle').innerText();
        await page.getByRole('button', {name: '다음', exact: true}).click();
        requireCheck(await page.locator('#viewerTitle').innerText() !== first, '다음 화면 실패');
        await page.keyboard.press('ArrowLeft');
        requireCheck(await page.locator('#viewerTitle').innerText() === first, '키보드 이전 화면 실패');
        await page.getByRole('button', {name: '원본 크기', exact: true}).click();
        requireCheck(await page.locator('#viewer').evaluate(view => view.classList.contains('zoom') && view.scrollWidth >= view.clientWidth), '원본 크기 실패');
        await page.keyboard.press('Escape');
        requireCheck(!await page.locator('#viewerDialog').evaluate(dialog => dialog.open), 'Esc 닫기 실패');
        await page.getByRole('button', {name: '전체', exact: true}).click();
        await page.locator('article').evaluateAll(cards => Promise.all(cards.map(card =>
        {
            const image = card.querySelector('img');
            image.loading = 'eager';
            return image.decode();
        })));
        const imageFailures = await page.locator('article img').evaluateAll(images => images.filter(image => !image.complete || !image.naturalWidth).length);
        requireCheck(!errors.length && !missing.length && !imageFailures, '이미지 또는 스크립트 오류');
        const report = {
            gallery_sha256: crypto.createHash('sha256').update(fs.readFileSync(gallery)).digest('hex'),
            gallery_screens: 84, search: true, workspace_filter: true, modal_open: true,
            next_previous: true, keyboard_navigation: true, original_size: true,
            escape_close: true, local_images_loaded: 84, page_errors: errors, missing_resources: missing
        };
        fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
        console.log(JSON.stringify(report));
    }
    finally
    {
        await browser.close();
    }
}

main().catch(error =>
{
    console.error(error);
    process.exitCode = 1;
});
