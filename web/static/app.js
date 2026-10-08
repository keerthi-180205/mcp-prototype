document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chatForm');
    const queryInput = document.getElementById('queryInput');
    const sendBtn = document.getElementById('sendBtn');
    const messagesContainer = document.getElementById('messagesContainer');
    const maxReelsInput = document.getElementById('maxReelsInput');
    const maxCommentsInput = document.getElementById('maxCommentsInput');
    const platformSelect = document.getElementById('platformSelect');
    const exportCsvBtn = document.getElementById('exportCsvBtn');

    let allExtractedRecords = [];

    // Auto resize textarea
    queryInput.addEventListener('input', () => {
        queryInput.style.height = 'auto';
        queryInput.style.height = `${Math.min(queryInput.scrollHeight, 120)}px`;
    });

    queryInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // Preset Buttons Click
    document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const query = btn.getAttribute('data-query');
            const targetPlatform = btn.getAttribute('data-platform');
            if (targetPlatform && platformSelect) {
                platformSelect.value = targetPlatform;
            }
            queryInput.value = query;
            queryInput.dispatchEvent(new Event('input'));
            chatForm.dispatchEvent(new Event('submit'));
        });
    });

    // Export CSV
    exportCsvBtn.addEventListener('click', () => {
        if (!allExtractedRecords.length) return;
        exportToCsv(allExtractedRecords);
    });

    // Form Submit
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = queryInput.value.trim();
        if (!query) return;

        const maxReels = parseInt(maxReelsInput ? maxReelsInput.value : 5) || 5;
        const maxComments = parseInt(maxCommentsInput ? maxCommentsInput.value : 25) || 25;

        // Add user message
        addUserMessage(query);
        queryInput.value = '';
        queryInput.style.height = 'auto';

        // Add thinking / pipeline progress message
        const thinkingId = addThinkingMessage();
        setSendLoading(true);

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: query,
                    max_reels: maxReels,
                    max_comments_per_reel: maxComments,
                }),
            });

            const data = await response.json();
            removeMessage(thinkingId);

            if (data.status === 'success') {
                addAssistantResponse(data);
                if (data.comments && data.comments.length) {
                    allExtractedRecords = [...allExtractedRecords, ...data.comments];
                    exportCsvBtn.style.display = 'flex';
                }
            } else {
                addErrorMessage(data.message || `An error occurred while fetching social intelligence.`);
            }
        } catch (err) {
            removeMessage(thinkingId);
            addErrorMessage(`Connection failed: ${err.message}. Please check if the web server is running.`);
        } finally {
            setSendLoading(false);
            scrollToBottom();
        }
    });

    function addUserMessage(text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message user-message';

        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = 'You';

        const content = document.createElement('div');
        content.className = 'message-content';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        const p = document.createElement('p');
        p.textContent = text;

        bubble.appendChild(p);
        content.appendChild(bubble);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(content);

        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
    }

    function addThinkingMessage() {
        const id = 'thinking-' + Date.now();
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';
        msgDiv.id = id;
        msgDiv.innerHTML = `
            <div class="avatar">AI</div>
            <div class="message-content">
                <div class="message-bubble">
                    <div class="pipeline-card">
                        <h4>
                            <span class="spinner"></span>
                            Universal Social Intelligence Pipeline Executing...
                        </h4>
                        <div class="pipeline-steps">
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Scanning reachable platforms via Agent Reach (YouTube, Reddit, X / Twitter, Instagram)...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Discovering top trending posts & videos...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Extracting commenter user IDs & exact public comments...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Ranking comments by engagement and deduplicating...</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
        return id;
    }

    function getPlatformStyle(platform) {
        const p = (platform || '').toLowerCase();
        if (p.includes('youtube')) {
            return 'background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);';
        } else if (p.includes('reddit')) {
            return 'background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.3);';
        } else if (p.includes('twitter') || p.includes(' x')) {
            return 'background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);';
        } else if (p.includes('instagram')) {
            return 'background: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3);';
        }
        return 'background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);';
    }

    function addAssistantResponse(data) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';

        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = 'AI';

        const content = document.createElement('div');
        content.className = 'message-content';
        content.style.maxWidth = '100%';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.style.maxWidth = '100%';

        const comments = data.comments || [];
        const totalComments = comments.length;
        const reachedStr = data.platform || (data.platforms_reached ? data.platforms_reached.join(', ') : 'Universal Reach');

        const p = document.createElement('p');
        p.style.fontSize = '0.95rem';
        p.style.marginBottom = '12px';
        p.textContent = data.chatbot_message || `Collected ${totalComments} public comments across ${reachedStr}:`;
        bubble.appendChild(p);

        const tableContainer = document.createElement('div');
        tableContainer.style.overflowX = 'auto';
        tableContainer.style.background = 'rgba(15, 23, 42, 0.7)';
        tableContainer.style.borderRadius = '10px';
        tableContainer.style.border = '1px solid var(--border)';

        const table = document.createElement('table');
        table.style.width = '100%';
        table.style.borderCollapse = 'collapse';
        table.style.fontSize = '0.85rem';
        table.style.color = '#cbd5e1';

        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        headRow.style.borderBottom = '1px solid var(--border)';
        headRow.style.background = 'rgba(0,0,0,0.3)';
        headRow.style.textAlign = 'left';

        ['User ID', 'Comment', 'Platform Name', 'Source Link'].forEach(headerText => {
            const th = document.createElement('th');
            th.style.padding = '10px 14px';
            th.textContent = headerText;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        if (comments.length === 0) {
            const emptyRow = document.createElement('tr');
            const emptyTd = document.createElement('td');
            emptyTd.colSpan = 4;
            emptyTd.style.padding = '24px';
            emptyTd.style.textAlign = 'center';
            emptyTd.style.color = '#94a3b8';
            emptyTd.textContent = 'No public comments found across reachable platforms. Try a broader topic term.';
            emptyRow.appendChild(emptyTd);
            tbody.appendChild(emptyRow);
        } else {
            comments.forEach(c => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid rgba(255,255,255,0.06)';

                // User TD
                const tdUser = document.createElement('td');
                tdUser.style.padding = '10px 14px';
                tdUser.style.fontWeight = '600';
                tdUser.style.color = '#93c5fd';
                tdUser.style.whiteSpace = 'nowrap';
                tdUser.style.verticalAlign = 'top';
                tdUser.textContent = c.user_id || c.username || 'anonymous';
                if (c.likes > 0) {
                    const likesDiv = document.createElement('div');
                    likesDiv.style.fontSize = '0.72rem';
                    likesDiv.style.color = '#64748b';
                    likesDiv.style.fontWeight = 'normal';
                    likesDiv.style.marginTop = '2px';
                    likesDiv.textContent = `❤️ ${c.likes.toLocaleString()} likes`;
                    tdUser.appendChild(likesDiv);
                }
                tr.appendChild(tdUser);

                // Comment TD
                const tdComment = document.createElement('td');
                tdComment.style.padding = '10px 14px';
                tdComment.style.lineHeight = '1.5';
                tdComment.style.color = '#e2e8f0';
                tdComment.style.verticalAlign = 'top';
                tdComment.textContent = c.comment || c.comment_text || '';
                tr.appendChild(tdComment);

                // Platform TD
                const tdPlat = document.createElement('td');
                tdPlat.style.padding = '10px 14px';
                tdPlat.style.textAlign = 'center';
                tdPlat.style.verticalAlign = 'top';
                tdPlat.style.whiteSpace = 'nowrap';

                const platBadge = document.createElement('span');
                platBadge.style.display = 'inline-block';
                platBadge.style.padding = '2px 8px';
                platBadge.style.borderRadius = '6px';
                platBadge.style.fontSize = '0.75rem';
                platBadge.style.fontWeight = '600';
                platBadge.style.cssText = getPlatformStyle(c.platform);
                platBadge.textContent = c.platform || 'Social';
                tdPlat.appendChild(platBadge);
                tr.appendChild(tdPlat);

                // Source Link TD
                const tdLink = document.createElement('td');
                tdLink.style.padding = '10px 14px';
                tdLink.style.textAlign = 'center';
                tdLink.style.verticalAlign = 'top';
                tdLink.style.whiteSpace = 'nowrap';
                const sourceUrl = c.link || c.post_url;
                if (sourceUrl) {
                    const a = document.createElement('a');
                    a.href = sourceUrl;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    a.style.display = 'inline-flex';
                    a.style.alignItems = 'center';
                    a.style.gap = '4px';
                    a.style.color = '#60a5fa';
                    a.style.background = 'rgba(59, 130, 246, 0.1)';
                    a.style.border = '1px solid rgba(59, 130, 246, 0.25)';
                    a.style.padding = '3px 8px';
                    a.style.borderRadius = '6px';
                    a.style.fontSize = '0.75rem';
                    a.style.textDecoration = 'none';
                    a.textContent = 'View Source ↗';
                    tdLink.appendChild(a);
                } else {
                    const spanNa = document.createElement('span');
                    spanNa.style.color = '#64748b';
                    spanNa.style.fontSize = '0.75rem';
                    spanNa.textContent = 'N/A';
                    tdLink.appendChild(spanNa);
                }
                tr.appendChild(tdLink);

                tbody.appendChild(tr);
            });
        }
        table.appendChild(tbody);
        tableContainer.appendChild(table);
        bubble.appendChild(tableContainer);
        content.appendChild(bubble);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(content);

        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
    }

    function addErrorMessage(errorText) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';

        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.style.background = '#ef4444';
        avatar.textContent = '!';

        const content = document.createElement('div');
        content.className = 'message-content';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.style.borderColor = '#ef4444';

        const pTitle = document.createElement('p');
        pTitle.style.color = '#fca5a5';
        const strong = document.createElement('strong');
        strong.textContent = 'Error during intelligence acquisition:';
        pTitle.appendChild(strong);

        const pDesc = document.createElement('p');
        pDesc.style.fontSize = '0.88rem';
        pDesc.style.marginTop = '6px';
        pDesc.textContent = errorText;

        bubble.appendChild(pTitle);
        bubble.appendChild(pDesc);
        content.appendChild(bubble);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(content);

        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
    }

    function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function setSendLoading(isLoading) {
        sendBtn.disabled = isLoading;
        sendBtn.innerHTML = isLoading 
            ? '<span class="spinner"></span>'
            : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function getBadgeClass(category) {
        if (!category) return 'anxiety';
        const lower = category.toLowerCase();
        if (lower.includes('work') || lower.includes('burnout')) return 'work';
        if (lower.includes('exam') || lower.includes('study')) return 'exam';
        if (lower.includes('stress')) return 'stress';
        return 'anxiety';
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function exportToCsv(records) {
        const headers = ['Username', 'User ID', 'Comment Text', 'Category', 'Likes', 'Post URL', 'Timestamp'];
        const rows = records.map(r => [
            `"${(r.user_handle || r.username || '').replace(/"/g, '""')}"`,
            `"${(r.user_id || '').replace(/"/g, '""')}"`,
            `"${(r.comment_text || r.comment || '').replace(/"/g, '""')}"`,
            `"${(r.category || '').replace(/"/g, '""')}"`,
            r.likes || 0,
            `"${(r.post_url || '').replace(/"/g, '""')}"`,
            `"${(r.created_at || '').replace(/"/g, '""')}"`,
        ]);

        const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `social_comments_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
});
