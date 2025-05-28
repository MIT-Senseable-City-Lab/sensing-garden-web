console.log('=== bbox_overlay_script included ===');
function drawSvgBbox(img, svg, bbox) {
    if (!bbox || bbox.length !== 4 || (bbox[0] === 0 && bbox[1] === 0 && bbox[2] === 0 && bbox[3] === 0)) return;
    // Use displayed size
    const displayW = img.clientWidth;
    const displayH = img.clientHeight;
    svg.setAttribute('width', displayW);
    svg.setAttribute('height', displayH);
    svg.style.width = displayW + 'px';
    svg.style.height = displayH + 'px';
    
    // Extract normalized values [x_center, y_center, width, height]
    let x_center = bbox[0];
    let y_center = bbox[1];
    let width = bbox[2];
    let height = bbox[3];
    
    // Calculate corner points from center and dimensions (matching Python reference)
    let xmin = Math.round((x_center - width/2) * displayW);
    let ymin = Math.round((y_center - height/2) * displayH);
    let xmax = Math.round((x_center + width/2) * displayW);
    let ymax = Math.round((y_center + height/2) * displayH);
    
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
    var modal = document.getElementById('imageModal');
    
    // Clear previous image and set new source
    modalImg.src = '';
    modalImg.src = imageUrl;
    
    function drawModalBbox() {
        console.log('[showModalWithImageAndBbox] Drawing bbox:', bbox);
        if (bbox && bbox.length === 4) {
            // Make sure SVG covers the image exactly
            modalSvg.style.position = 'absolute';
            modalSvg.style.top = modalImg.offsetTop + 'px';
            modalSvg.style.left = modalImg.offsetLeft + 'px';
            modalSvg.style.width = modalImg.width + 'px';
            modalSvg.style.height = modalImg.height + 'px';
            
            drawSvgBbox(modalImg, modalSvg, bbox);
            modalSvg.style.display = '';
        } else {
            modalSvg.style.display = 'none';
        }
    }
    
    // Set up modal event handlers for responsive behavior
    if (window.$ && modal) {
        $(modal).on('shown.bs.modal', function() {
            // Redraw bbox after modal is fully shown and sized
            setTimeout(drawModalBbox, 100);
        });
        
        // Handle window resize to reposition bbox
        $(window).on('resize', function() {
            if ($(modal).hasClass('show')) {
                drawModalBbox();
            }
        });
    }
    
    // Initial draw attempt
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
