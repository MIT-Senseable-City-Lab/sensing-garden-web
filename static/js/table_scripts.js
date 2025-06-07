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
    var pageLimitAttr = parseInt(tableElement.data('page-limit'));
    if (isNaN(pageLimitAttr)) {
        pageLimitAttr = tableElement.find('tbody tr').length;
    }
    var table = tableElement.DataTable({
        paging: false,
        searching: false,
        ordering: false,
        info: false,
        pageLength: pageLimitAttr,
        dom: 't',
        autoWidth: true,
        responsive: true,
        scrollX: true,
        scrollCollapse: true
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

function changeLimit(value) {
    if (!value) return;
    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('limit', value);
    currentUrl.searchParams.delete('next_token');
    currentUrl.searchParams.delete('prev_token');
    currentUrl.searchParams.set('page', '1');
    window.location.href = currentUrl.toString();
}

function changeLimit(value) {
    if (!value) return;
    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('limit', value);
    currentUrl.searchParams.delete('next_token');
    currentUrl.searchParams.delete('prev_token');
    currentUrl.searchParams.set('page', '1');
    window.location.href = currentUrl.toString();
}
