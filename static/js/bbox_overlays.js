console.log('=== bbox_overlay_script included ===');
var modalImages = [];
var currentModalIndex = -1;
var prevBtn = null;
var nextBtn = null;
var modalTitle = null;
var currentModalImageUrl = null;
var currentModalBbox = null;
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

function drawCanvasBbox(img, canvas, bbox) {
    var ctx = canvas.getContext('2d');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    if (!bbox || bbox.length !== 4 || (bbox[0] === 0 && bbox[1] === 0 && bbox[2] === 0 && bbox[3] === 0)) return;
    var xmin = (bbox[0] - bbox[2]/2) * canvas.width;
    var ymin = (bbox[1] - bbox[3]/2) * canvas.height;
    var width = bbox[2] * canvas.width;
    var height = bbox[3] * canvas.height;
    ctx.strokeStyle = '#ff0000';
    ctx.lineWidth = 2;
    ctx.strokeRect(xmin, ymin, width, height);
}

function downloadCurrentImageWithBbox() {
    var modalImg = document.getElementById('modal-image');
    if (!modalImg || !currentModalImageUrl) return;
    var canvas = document.createElement('canvas');
    drawCanvasBbox(modalImg, canvas, currentModalBbox);
    try {
        var dataUrl = canvas.toDataURL('image/png');
        var link = document.createElement('a');
        link.href = dataUrl;
        link.download = 'image_with_bbox.png';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } catch (err) {
        console.error('Failed to generate image for download', err);
        alert('Unable to download image. This image may not allow cross-origin access.');
    }
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

    currentModalImageUrl = imageUrl;
    currentModalBbox = bbox;
    
    // Clear previous image and set new source with CORS enabled
    modalImg.crossOrigin = 'anonymous';
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

function showModalForIndex(index) {
    if (index < 0 || index >= modalImages.length) return;
    currentModalIndex = index;
    var img = modalImages[index];
    var bboxStr = img.getAttribute('data-bbox');
    var bbox = null;
    try { if (bboxStr) bbox = JSON.parse(bboxStr); } catch (e) {}
    showModalWithImageAndBbox(img.getAttribute('data-image-url'), bbox);
    if (modalTitle) {
        var ts = img.getAttribute('data-timestamp');
        modalTitle.textContent = ts ? 'Image Preview - ' + ts : 'Image Preview';
    }
    if (prevBtn) {
        prevBtn.style.display = index <= 0 ? 'none' : 'block';
    }
    if (nextBtn) {
        nextBtn.style.display = index >= modalImages.length - 1 ? 'none' : 'block';
    }
    if (window.$ && $('#imageModal').modal) {
        $('#imageModal').modal('show');
    }
}

document.addEventListener('DOMContentLoaded', function () {
    renderBboxOverlays();
    modalTitle = document.getElementById('imageModalLabel');
    modalImages = Array.from(document.querySelectorAll('.clickable-image'));
    modalImages.forEach(function (img, idx) {
        img.dataset.modalIndex = idx;
        img.addEventListener('click', function () {
            showModalForIndex(idx);
        });
    });

    prevBtn = document.getElementById('modal-prev');
    nextBtn = document.getElementById('modal-next');
    var downloadBtn = document.getElementById('modal-download');
    if (prevBtn) {
        prevBtn.addEventListener('click', function () {
            if (currentModalIndex > 0) {
                showModalForIndex(currentModalIndex - 1);
            }
        });
    }
    if (nextBtn) {
        nextBtn.addEventListener('click', function () {
            if (currentModalIndex < modalImages.length - 1) {
                showModalForIndex(currentModalIndex + 1);
            }
        });
    }
    if (downloadBtn) {
        downloadBtn.addEventListener('click', downloadCurrentImageWithBbox);
    }

    // Allow arrow key navigation while modal is open
    document.addEventListener('keydown', function (e) {
        var modal = document.getElementById('imageModal');
        if (!modal || !modal.classList.contains('show')) return;
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            if (currentModalIndex > 0) {
                showModalForIndex(currentModalIndex - 1);
            }
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            if (currentModalIndex < modalImages.length - 1) {
                showModalForIndex(currentModalIndex + 1);
            }
        }
    });

    window.addEventListener('resize', renderBboxOverlays);
});

