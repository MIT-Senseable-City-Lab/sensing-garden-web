// Table scripts for DataTables initialization and search
function initDataTable(tableId) {
    if (typeof $ === 'undefined' || typeof $.fn.DataTable === 'undefined') {
        console.error('jQuery or DataTable not loaded');
        return;
    }
    var tableElement = $('#' + tableId);
    if (tableElement.length === 0) {
        console.error('Table element #' + tableId + ' not found');
        return;
    }
    if ($.fn.DataTable.isDataTable('#' + tableId)) {
        $('#' + tableId).DataTable().destroy();
    }
    tableElement.addClass('dt-table-' + tableId);
    var table = tableElement.DataTable({
        paging: true,
        searching: false,
        ordering: false,
        info: true,
        lengthMenu: [[10, 25, 50, -1], [10, 25, 50, 'All']],
        dom: 't',
        autoWidth: true,
        responsive: true,
        scrollX: true,
        scrollCollapse: true,
        initComplete: function () {
            // Length control
            var lengthHtml = '<label>Show <select name="' + tableId + '_length" aria-controls="' + tableId + '" class="form-select form-select-sm">' +
                '<option value="10">10</option>' +
                '<option value="25">25</option>' +
                '<option value="50">50</option>' +
                '<option value="-1">All</option>' +
                '</select> entries</label>';
            $('#' + tableId + '_length').html(lengthHtml);
            // Connect length control
            $('#' + tableId + '_length select').on('change', function () {
                table.page.len($(this).val()).draw();
            });
            // Info display
            var updateInfo = function () {
                var info = table.page.info();
                var infoText = 'Showing ' + (info.start + 1) + ' to ' + info.end + ' of ' + info.recordsDisplay + ' entries';
                if (info.recordsDisplay != info.recordsTotal) {
                    infoText += ' (filtered from ' + info.recordsTotal + ' total entries)';
                }
                $('#' + tableId + '_info').html(infoText);
            };
            updateInfo();
            table.on('draw', updateInfo);
            // Pagination
            var createPagination = function () {
                var info = table.page.info();
                var html = '<ul class="pagination">';
                html += '<li class="paginate_button page-item previous ' + (info.page === 0 ? 'disabled' : '') + '">' +
                    '<a href="#" class="page-link" data-page="prev">Previous</a></li>';
                var startPage = Math.max(0, info.page - 2);
                var endPage = Math.min(info.pages - 1, info.page + 2);
                if (startPage > 0) {
                    html += '<li class="paginate_button page-item"><a href="#" class="page-link" data-page="0">1</a></li>';
                    if (startPage > 1) html += '<li class="paginate_button page-item disabled"><a href="#" class="page-link">...</a></li>';
                }
                for (var i = startPage; i <= endPage; i++) {
                    html += '<li class="paginate_button page-item ' + (i === info.page ? 'active' : '') + '">' +
                        '<a href="#" class="page-link" data-page="' + i + '">' + (i + 1) + '</a></li>';
                }
                if (endPage < info.pages - 1) {
                    if (endPage < info.pages - 2) html += '<li class="paginate_button page-item disabled"><a href="#" class="page-link">...</a></li>';
                    html += '<li class="paginate_button page-item"><a href="#" class="page-link" data-page="' + (info.pages - 1) + '">' + info.pages + '</a></li>';
                }
                html += '<li class="paginate_button page-item next ' + (info.page === info.pages - 1 ? 'disabled' : '') + '">' +
                    '<a href="#" class="page-link" data-page="next">Next</a></li>';
                html += '</ul>';
                $('#' + tableId + '_paginate').html(html);
                // Event handlers
                $('#' + tableId + '_paginate .page-link').on('click', function (e) {
                    e.preventDefault();
                    var page = $(this).data('page');
                    if (page === 'prev') {
                        table.page('previous').draw('page');
                    } else if (page === 'next') {
                        table.page('next').draw('page');
                    } else {
                        table.page(page).draw('page');
                    }
                });
            };
            createPagination();
            table.on('draw', createPagination);
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    var tables = document.querySelectorAll('[data-table-id]');
    tables.forEach(function (el) {
        var tableId = el.getAttribute('data-table-id');
        if (tableId) {
            initDataTable(tableId);
        }
    });
});

function downloadCSV(url) {
    window.open(url, '_blank');
}

function sortTable(tableId, value) {
    if (!value) return;
    const [field, order] = value.split('_');
    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('sort_by', field);
    currentUrl.searchParams.set('sort_desc', order === 'desc');
    currentUrl.searchParams.delete('next_token');
    currentUrl.searchParams.delete('prev_token');
    currentUrl.searchParams.set('page', '1');
    window.location.href = currentUrl.toString();
}
