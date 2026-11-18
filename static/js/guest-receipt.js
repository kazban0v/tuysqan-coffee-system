'use strict';
function localizeGuestReceipt(){document.querySelectorAll('[data-receipt-amount]').forEach(el=>el.textContent=money(el.dataset.receiptAmount))}
localizeGuestReceipt();$$('[data-set-language]').forEach(button=>button.addEventListener('click',localizeGuestReceipt));
