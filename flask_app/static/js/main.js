// Auto-hide flash messages (handled by SweetAlert2 in base.html)
document.addEventListener('DOMContentLoaded', function() {
    // Flash messages are now handled by SweetAlert2 Toast in base.html
    // This section is kept for backward compatibility but can be removed
    
    // Note: Confirm delete actions are now handled by setupConfirmButtons() in base.html
    // using SweetAlert2 for all [data-confirm] buttons
});

// Modal functions
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'flex';
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

// Close modal when clicking on overlay or modal background
window.addEventListener('click', function(e) {
    if (e.target.classList.contains('modal') || e.target.classList.contains('modal-overlay')) {
        const modal = e.target.classList.contains('modal') ? e.target : e.target.closest('.modal');
        if (modal) {
            modal.style.display = 'none';
            modal.classList.remove('active');
            document.body.style.overflow = 'auto';
        }
    }
});

// Close modal with ESC key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        const activeModals = document.querySelectorAll('.modal.active');
        activeModals.forEach(modal => {
            modal.style.display = 'none';
            modal.classList.remove('active');
            document.body.style.overflow = 'auto';
        });
    }
});

// Form validation helper
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return true;
    
    const inputs = form.querySelectorAll('[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.classList.add('error');
            isValid = false;
        } else {
            input.classList.remove('error');
        }
    });
    
    return isValid;
}

// Auto-refresh for chat (every 5 seconds)
if (window.location.pathname.includes('/chat')) {
    setInterval(() => {
        const chatMessages = document.querySelector('.chat-messages');
        if (chatMessages) {
            // Reload messages via AJAX
            const currentScroll = chatMessages.scrollTop;
            fetch(window.location.href)
                .then(r => r.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newMessages = doc.querySelector('.chat-messages');
                    if (newMessages) {
                        chatMessages.innerHTML = newMessages.innerHTML;
                        // Maintain scroll position if user didn't scroll
                        if (Math.abs(chatMessages.scrollHeight - currentScroll - chatMessages.clientHeight) < 50) {
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        }
                    }
                });
        }
    }, 5000);
}
