'use strict';
function localizeGuestLoyalty(){document.querySelectorAll('[data-loyalty-amount]').forEach(el=>el.textContent=money(el.dataset.loyaltyAmount))}
localizeGuestLoyalty();$$('[data-set-language]').forEach(button=>button.addEventListener('click',localizeGuestLoyalty));
