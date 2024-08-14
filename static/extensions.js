function confirmModal(title, content, func) {
    $('#confirm_title').html(title);
    $('#confirm_body').html(content);
    $('#confirm_button').off('click');
    $('#confirm_button').on('click', func);
    $("#confirm_modal").modal({backdrop: 'static', keyboard: true}, 'show');
}

function copyToClipboard(text) {
    if ( ! window.navigator.clipboard ) {
        notify('클립보드 접근 권한이 없습니다.', 'warning');
    } else {
        window.navigator.clipboard.writeText(text).then(() => {
            notify('클립보드에 복사하였습니다.', 'success');
        },() => {
            notify('클립보드 복사에 실패했습니다.', 'warning');
        });
    }
}

function pagination(target, page, total, limit, listFunc) {
    target.empty();
    let limit_page = 10;
    let final_page = Math.ceil(total / limit);
    let elements;
    if (final_page > 1) {
        let first_page = Math.floor(page / limit_page) * limit_page;
        if (page < limit_page) {
            first_page++;
        }
        let last_page = Math.min(first_page + limit_page, final_page);
        elements = '<ul class="pagination justify-content-center">';
        if (first_page >= limit_page) {
            elements += '<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>';
        }
        elements += '<li class="page-item' + (first_page < limit_page ? ' disabled' : '') + '">';
        elements += '<a class="page-link" aria-label="Previous" data-page="' + (first_page - 1) + '"><span aria-hidden="true">&laquo;</span></a></li>';
        for (i = first_page; i <= last_page; i++) {
            elements += '<li class="page-item' + (i == page ? ' active" aria-current="page"' : '"') + '>';
            elements += '<a class="page-link" href="#" data-page="' + i + '">' + i + '</a></li>';
        }
        elements += '<li class="page-item' + (last_page >= final_page ? ' disabled' : '') + '">';
        elements += '<a class="page-link" href="#" aria-label="Next" data-page="' + (last_page + 1) +'"><span aria-hidden="true">&raquo;</span></a></li>';
        if (last_page < final_page) {
            elements += '<li class="page-item"><a class="page-link" href="#" data-page="' + final_page + '">' + final_page + '</a></li></ul>';
        }
    } else {
        elements = '<ul class="pagination justify-content-center">';
        elements += '<li class="page-item disabled"><a class="page-link" aria-label="Previous"><span aria-hidden="true">&laquo;</span></a></li>';
        elements += '<li class="page-item disabled"><a class="page-link disabled" href="#">1</a></li>';
        elements += '<li class="page-item disabled"><a class="page-link" href="#"  aria-label="Next"><span aria-hidden="true">&raquo;</span></a></li></ul>';
    }
    target.append(elements);
    $('.page-link').on('click', function(e) {
        listFunc($(this).data('page'));
    });
}