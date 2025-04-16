console.log('=== bbox_overlay_script included ===');
function drawSvgBbox(img, svg, bbox) {
    if (!bbox || bbox.length !== 4 || (bbox[0] === 0 && bbox[1] === 0 && bbox[2] === 1 && bbox[3] === 1)) return;
    // Use displayed size
    const displayW = img.clientWidth;
    const displayH = img.clientHeight;
    svg.setAttribute('width', displayW);
    svg.setAttribute('height', displayH);
    svg.style.width = displayW + 'px';
    svg.style.height = displayH + 'px';
    let xmin = bbox[0] * displayW;
    let ymin = bbox[1] * displayH;
    let xmax = bbox[2] * displayW;
    let ymax = bbox[3] * displayH;
    const points = `${xmin},${ymin} ${xmax},${ymin} ${xmax},${ymax} ${xmin},${ymax}`;
    const poly = svg.querySelector('polygon');
    if (poly) poly.setAttribute('points', points);
    // Debug logging
    console.log('[drawSvgBbox] bbox:', bbox, 'img:', displayW, displayH, 'svg:', svg.getAttribute('width'), svg.getAttribute('height'), 'points:', points);
}

function renderBboxOverlays() {
    console.log('[renderBboxOverlays] running');
    var imgs = document.querySelectorAll('.detection-img');
    if (imgs.length === 0) {
        console.log('[renderBboxOverlays] No .detection-img found');
    }
    imgs.forEach(function (img) {
        var bboxStr = img.getAttribute('data-bbox');
        if (!bboxStr) {
            console.log('[renderBboxOverlays] data-bbox missing for image', img);
            return;
        }
        console.log('[renderBboxOverlays] Processing image with data-bbox:', bboxStr);
        var bbox;
        try { bbox = JSON.parse(bboxStr); } catch (e) { console.log('[renderBboxOverlays] JSON parse error', e); return; }
        var svg = img.parentNode.querySelector('.bbox-svg-overlay');
        if (!svg) {
            console.log('[renderBboxOverlays] No svg sibling found for image');
            return;
        }
        function draw() { drawSvgBbox(img, svg, bbox); }
        if (img.complete) {
            draw();
        } else {
            img.onload = draw;
        }
    });
}

function showModalWithImageAndBbox(imageUrl, bbox) {
    var modalImg = document.getElementById('modal-image');
    var modalSvg = document.getElementById('modal-bbox-svg');
    modalImg.src = imageUrl;
    function drawModalBbox() {
        if (bbox && bbox.length === 4) {
            drawSvgBbox(modalImg, modalSvg, bbox);
            modalSvg.style.display = '';
        } else {
            modalSvg.style.display = 'none';
        }
    }
    modalImg.onload = drawModalBbox;
    if (modalImg.complete) drawModalBbox();
}

document.addEventListener('DOMContentLoaded', function () {
    renderBboxOverlays();
    document.querySelectorAll('.clickable-image').forEach(function (img) {
        img.addEventListener('click', function () {
            var bboxStr = img.getAttribute('data-bbox');
            var bbox = null;
            try { if (bboxStr) bbox = JSON.parse(bboxStr); } catch (e) { }
            showModalWithImageAndBbox(img.getAttribute('data-image-url'), bbox);
            if (window.$ && $('#imageModal').modal) {
                $('#imageModal').modal('show');
            }
        });
    });
    window.addEventListener('resize', renderBboxOverlays);
});
