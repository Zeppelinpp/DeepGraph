class DeepGraphLogger {
    constructor() {
        this.ws = null;
        this.sessions = [];
        this.currentSessionId = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.connectWebSocket();
        this.loadSessions();
    }

    setupEventListeners() {
        // 运行按钮
        const runButton = document.getElementById('runButton');
        const queryInput = document.getElementById('queryInput');
        
        runButton.addEventListener('click', () => this.runAnalysis());
        queryInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.runAnalysis();
            }
        });

        // 刷新按钮
        document.getElementById('refreshButton').addEventListener('click', () => {
            this.loadSessions();
        });

        // 关闭任务面板
        document.getElementById('closeTasks').addEventListener('click', () => {
            this.closeTasks();
        });
        
        // 切换日志显示
        document.getElementById('toggleLogs').addEventListener('click', () => {
            this.toggleLogs();
        });

        // ESC键关闭任务面板
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeTasks();
            }
        });
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.updateConnectionStatus('connected');
                this.reconnectAttempts = 0;
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleWebSocketMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.updateConnectionStatus('disconnected');
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus('disconnected');
            };

        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
            this.updateConnectionStatus('disconnected');
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            
            this.updateConnectionStatus('connecting');
            setTimeout(() => {
                console.log(`Attempting to reconnect... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
                this.connectWebSocket();
            }, delay);
        }
    }

    updateConnectionStatus(status) {
        const statusElement = document.getElementById('connectionStatus');
        const statusText = statusElement.querySelector('span');
        
        statusElement.className = `connection-status ${status}`;
        
        switch (status) {
            case 'connected':
                statusText.textContent = '已连接';
                break;
            case 'connecting':
                statusText.textContent = '重连中...';
                break;
            case 'disconnected':
                statusText.textContent = '连接断开';
                break;
        }
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'sessions_list':
                this.sessions = data.sessions;
                this.renderSessions();
                break;
            case 'session_start':
                this.sessions.unshift(data.session);
                this.renderSessions();
                this.selectSession(data.session.id);
                break;
            case 'session_end':
                this.updateSession(data.session);
                break;
            case 'new_log':
                this.addLogEntry(data.session_id, data.log);
                break;
            case 'task_created':
                this.addTaskCard(data.session_id, data.task);
                break;
            case 'task_updated':
                this.updateTaskCard(data.session_id, data.task);
                break;
            case 'tool_call_added':
                this.addToolCallToTask(data.session_id, data.task_name, data.tool_call);
                break;
            default:
                console.log('Unknown message type:', data.type);
        }
    }

    async runAnalysis() {
        const queryInput = document.getElementById('queryInput');
        const runButton = document.getElementById('runButton');
        const query = queryInput.value.trim();

        if (!query) {
            this.showNotification('请输入分析问题', 'warning');
            return;
        }

        try {
            runButton.disabled = true;
            this.showLoading(true);

            const response = await fetch('/api/run', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query }),
            });

            const result = await response.json();

            if (response.ok) {
                this.showNotification('分析已开始', 'success');
                queryInput.value = '';
                this.currentSessionId = result.session_id;
            } else {
                this.showNotification(result.detail || '启动分析失败', 'error');
            }

        } catch (error) {
            console.error('Error running analysis:', error);
            this.showNotification('网络错误，请重试', 'error');
        } finally {
            runButton.disabled = false;
            this.showLoading(false);
        }
    }

    async loadSessions() {
        try {
            const response = await fetch('/api/sessions');
            const data = await response.json();
            this.sessions = data.sessions;
            this.renderSessions();
        } catch (error) {
            console.error('Error loading sessions:', error);
            this.showNotification('加载会话失败', 'error');
        }
    }

    renderSessions() {
        const sessionsList = document.getElementById('sessionsList');
        
        if (this.sessions.length === 0) {
            sessionsList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <p>暂无分析记录</p>
                    <p class="empty-state-hint">开始一个新的财务分析来查看日志</p>
                </div>
            `;
            return;
        }

        sessionsList.innerHTML = this.sessions.map(session => `
            <div class="session-item ${session.id === this.currentSessionId ? 'active' : ''}" 
                 onclick="logger.selectSession('${session.id}')">
                <div class="session-header">
                    <div class="session-status ${session.status}">
                        ${this.getStatusText(session.status)}
                    </div>
                </div>
                <div class="session-query">${this.escapeHtml(session.query)}</div>
                <div class="session-meta">
                    <div class="session-time">
                        <i class="fas fa-clock"></i>
                        ${this.formatTime(session.start_time)}
                    </div>
                    <div class="session-stats">
                        <div class="stat-item">
                            <i class="fas fa-list"></i>
                            ${session.log_count}条日志
                        </div>
                        ${session.duration_ms ? `
                            <div class="stat-item">
                                <i class="fas fa-stopwatch"></i>
                                ${this.formatDuration(session.duration_ms)}
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `).join('');
    }

    async selectSession(sessionId) {
        this.currentSessionId = sessionId;
        this.renderSessions();

        try {
            const response = await fetch(`/api/sessions/${sessionId}`);
            const session = await response.json();
            this.showTasks(session);
        } catch (error) {
            console.error('Error loading session details:', error);
            this.showNotification('加载会话详情失败', 'error');
        }
    }

    showTasks(session) {
        const tasksPanel = document.getElementById('tasksPanel');
        const tasksPanelTitle = document.getElementById('tasksPanelTitle');
        const sessionStatus = document.getElementById('sessionStatus');
        const sequentialTasks = document.getElementById('sequentialTasks');
        const parallelTasks = document.getElementById('parallelTasks');
        const sequentialCount = document.getElementById('sequentialCount');
        const parallelCount = document.getElementById('parallelCount');
        const logsContent = document.getElementById('logsContent');

        tasksPanelTitle.innerHTML = `
            <i class="fas fa-tasks"></i>
            ${this.escapeHtml(session.query)}
        `;

        sessionStatus.innerHTML = `
            <div class="session-status ${session.status}">
                ${this.getStatusText(session.status)}
            </div>
        `;

        // 渲染Sequential任务
        const sequentialTaskCards = session.sequential_tasks || [];
        sequentialTasks.innerHTML = sequentialTaskCards.map(task => this.renderTaskCard(task)).join('');
        sequentialCount.textContent = sequentialTaskCards.length;

        // 渲染Parallel任务
        const parallelTaskCards = session.parallel_tasks || [];
        parallelTasks.innerHTML = parallelTaskCards.map(task => this.renderTaskCard(task)).join('');
        parallelCount.textContent = parallelTaskCards.length;

        // 渲染传统日志
        logsContent.innerHTML = session.logs.map(log => this.renderLogEntry(log)).join('');
        
        tasksPanel.style.display = 'flex';
        
        // 滚动到底部
        setTimeout(() => {
            logsContent.scrollTop = logsContent.scrollHeight;
        }, 100);
    }

    renderTaskCard(task) {
        const statusIcon = this.getTaskStatusIcon(task.status);
        const toolCallsCount = task.tool_calls ? task.tool_calls.length : 0;
        
        return `
            <div class="task-card ${task.status}" data-task-id="${task.id}">
                <div class="task-header">
                    <div class="task-title">
                        ${statusIcon}
                        <span>${this.escapeHtml(task.name)}</span>
                    </div>
                    <div class="task-status ${task.status}">
                        ${this.getStatusText(task.status)}
                    </div>
                </div>
                
                <div class="task-description">
                    ${this.escapeHtml(task.description)}
                </div>
                
                <div class="task-meta">
                    <div class="task-timing">
                        ${task.start_time ? `
                            <div class="meta-item">
                                <i class="fas fa-play"></i>
                                ${this.formatTime(task.start_time)}
                            </div>
                        ` : ''}
                        ${task.duration_ms ? `
                            <div class="meta-item">
                                <i class="fas fa-stopwatch"></i>
                                ${this.formatDuration(task.duration_ms)}
                            </div>
                        ` : ''}
                    </div>
                    
                    <div class="task-stats">
                        <div class="meta-item">
                            <i class="fas fa-tools"></i>
                            ${toolCallsCount} 工具调用
                        </div>
                    </div>
                </div>
                
                ${toolCallsCount > 0 ? `
                    <div class="task-tools-toggle" onclick="logger.toggleTaskTools('${task.id}')">
                        <div class="toggle-content">
                            <i class="fas fa-tools"></i>
                            <span>查看工具调用 (${toolCallsCount})</span>
                        </div>
                        <i class="fas fa-chevron-down toggle-icon"></i>
                    </div>
                    
                    <div class="task-tools" id="tools-${task.id}">
                        ${task.tool_calls.map(toolCall => this.renderToolCall(toolCall)).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    }
    
    renderToolCall(toolCall) {
        return `
            <div class="tool-call" data-tool-id="${toolCall.id}">
                <div class="tool-header">
                    <div class="tool-name">
                        <i class="fas fa-wrench"></i>
                        ${this.escapeHtml(toolCall.tool_name)}
                    </div>
                    <div class="tool-duration">
                        ${toolCall.duration_ms ? this.formatDuration(toolCall.duration_ms) : ''}
                    </div>
                </div>
                
                <div class="tool-args">
                    <strong>参数:</strong>
                    <pre>${this.escapeHtml(JSON.stringify(toolCall.tool_args, null, 2))}</pre>
                </div>
                
                <div class="tool-result">
                    <strong>结果:</strong>
                    <div class="result-content">
                        ${this.escapeHtml(toolCall.tool_result)}
                    </div>
                </div>
                
                <div class="tool-timestamp">
                    <i class="fas fa-clock"></i>
                    ${this.formatTime(toolCall.timestamp)}
                </div>
            </div>
        `;
    }

    renderLogEntry(log) {
        return `
            <div class="log-entry ${log.level}" data-log-id="${log.id}">
                <div class="log-header">
                    <div class="log-title">${this.escapeHtml(log.title)}</div>
                    <div class="log-type ${log.type}">${this.getLogTypeText(log.type)}</div>
                </div>
                <div class="log-content">${this.escapeHtml(log.content)}</div>
                ${log.details ? `
                    <div class="log-details" style="display: none;">
                        <pre>${this.escapeHtml(JSON.stringify(log.details, null, 2))}</pre>
                    </div>
                ` : ''}
                <div class="log-meta">
                    <div class="log-timestamp">
                        <i class="fas fa-clock"></i>
                        ${this.formatTime(log.timestamp)}
                    </div>
                    ${log.duration_ms ? `
                        <div class="log-duration">
                            <i class="fas fa-stopwatch"></i>
                            ${this.formatDuration(log.duration_ms)}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    addLogEntry(sessionId, log) {
        if (sessionId === this.currentSessionId) {
            const logsContent = document.getElementById('logsContent');
            if (logsContent) {
                const logElement = document.createElement('div');
                logElement.innerHTML = this.renderLogEntry(log);
                logsContent.appendChild(logElement.firstElementChild);
                
                // 滚动到底部
                logsContent.scrollTop = logsContent.scrollHeight;
            }
        }

        // 更新会话统计
        const session = this.sessions.find(s => s.id === sessionId);
        if (session) {
            session.log_count = (session.log_count || 0) + 1;
            this.renderSessions();
        }
    }

    updateSession(session) {
        const index = this.sessions.findIndex(s => s.id === session.id);
        if (index !== -1) {
            this.sessions[index] = session;
            this.renderSessions();
            
            // 如果当前正在查看这个会话，更新状态
            if (this.currentSessionId === session.id) {
                const sessionStatus = document.getElementById('sessionStatus');
                if (sessionStatus) {
                    sessionStatus.innerHTML = `
                        <div class="session-status ${session.status}">
                            ${this.getStatusText(session.status)}
                        </div>
                    `;
                }
            }
        }
    }

    addTaskCard(sessionId, task) {
        if (sessionId === this.currentSessionId) {
            const targetContainer = task.execution_type === 'Sequential' ? 
                document.getElementById('sequentialTasks') : 
                document.getElementById('parallelTasks');
            
            const countElement = task.execution_type === 'Sequential' ?
                document.getElementById('sequentialCount') :
                document.getElementById('parallelCount');
            
            if (targetContainer) {
                const taskElement = document.createElement('div');
                taskElement.innerHTML = this.renderTaskCard(task);
                targetContainer.appendChild(taskElement.firstElementChild);
                
                // 更新计数
                const currentCount = parseInt(countElement.textContent) || 0;
                countElement.textContent = currentCount + 1;
            }
        }
    }
    
    updateTaskCard(sessionId, task) {
        if (sessionId === this.currentSessionId) {
            const taskElement = document.querySelector(`[data-task-id="${task.id}"]`);
            if (taskElement) {
                taskElement.outerHTML = this.renderTaskCard(task);
            }
        }
    }
    
    addToolCallToTask(sessionId, taskName, toolCall) {
        if (sessionId === this.currentSessionId) {
            // 找到对应的任务卡片并添加工具调用
            const taskCards = document.querySelectorAll('.task-card');
            for (const card of taskCards) {
                const taskTitle = card.querySelector('.task-title span');
                if (taskTitle && taskTitle.textContent.trim() === taskName) {
                    let toolsContainer = card.querySelector('.task-tools');
                    if (!toolsContainer) {
                        // 如果还没有工具调用容器，创建一个
                        const toggleButton = document.createElement('div');
                        toggleButton.className = 'task-tools-toggle';
                        toggleButton.onclick = () => this.toggleTaskTools(card.dataset.taskId);
                        toggleButton.innerHTML = `
                            <div class="toggle-content">
                                <i class="fas fa-tools"></i>
                                <span>查看工具调用 (1)</span>
                            </div>
                            <i class="fas fa-chevron-down toggle-icon"></i>
                        `;
                        card.appendChild(toggleButton);
                        
                        toolsContainer = document.createElement('div');
                        toolsContainer.className = 'task-tools expanded';
                        toolsContainer.id = `tools-${card.dataset.taskId}`;
                        card.appendChild(toolsContainer);
                        
                        // 自动展开新的工具调用
                        toggleButton.classList.add('expanded');
                        toggleButton.querySelector('.toggle-icon').className = 'fas fa-chevron-up toggle-icon';
                    }
                    
                    // 添加新的工具调用
                    const toolElement = document.createElement('div');
                    toolElement.innerHTML = this.renderToolCall(toolCall);
                    toolsContainer.appendChild(toolElement.firstElementChild);
                    
                    // 更新工具调用计数
                    const statsElement = card.querySelector('.task-stats .meta-item');
                    const toggleSpan = card.querySelector('.task-tools-toggle .toggle-content span');
                    
                    if (statsElement) {
                        const currentCount = parseInt(statsElement.textContent.match(/\d+/)[0]) || 0;
                        const newCount = currentCount + 1;
                        statsElement.innerHTML = `
                            <i class="fas fa-tools"></i>
                            ${newCount} 工具调用
                        `;
                        
                        // 同时更新切换按钮的计数
                        if (toggleSpan) {
                            toggleSpan.textContent = `查看工具调用 (${newCount})`;
                        }
                    }
                    
                    // 添加新工具调用的闪烁效果
                    const newToolCall = toolsContainer.lastElementChild;
                    if (newToolCall) {
                        newToolCall.style.animation = 'fadeInUp 0.3s ease';
                        setTimeout(() => {
                            newToolCall.style.animation = '';
                        }, 300);
                    }
                    break;
                }
            }
        }
    }
    
    toggleTaskTools(taskId) {
        const toolsContainer = document.getElementById(`tools-${taskId}`);
        const toggleButton = document.querySelector(`[data-task-id="${taskId}"] .task-tools-toggle`);
        const toggleIcon = toggleButton.querySelector('.toggle-icon');
        
        if (toolsContainer && toggleButton) {
            const isExpanded = toolsContainer.classList.contains('expanded');
            
            if (isExpanded) {
                // 收起
                toolsContainer.classList.remove('expanded');
                toggleButton.classList.remove('expanded');
                toggleIcon.className = 'fas fa-chevron-down toggle-icon';
            } else {
                // 展开
                toolsContainer.classList.add('expanded');
                toggleButton.classList.add('expanded');
                toggleIcon.className = 'fas fa-chevron-up toggle-icon';
            }
        }
    }
    
    toggleLogs() {
        const logsContent = document.getElementById('logsContent');
        const toggleButton = document.getElementById('toggleLogs').querySelector('i');
        
        const isVisible = logsContent.style.display !== 'none';
        logsContent.style.display = isVisible ? 'none' : 'block';
        toggleButton.className = isVisible ? 'fas fa-chevron-down' : 'fas fa-chevron-up';
    }

    closeTasks() {
        document.getElementById('tasksPanel').style.display = 'none';
        this.currentSessionId = null;
        this.renderSessions();
    }

    showNotification(message, type = 'info') {
        const notifications = document.getElementById('notifications');
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <i class="fas fa-${this.getNotificationIcon(type)}"></i>
                <span>${this.escapeHtml(message)}</span>
            </div>
        `;

        notifications.appendChild(notification);

        // 自动移除通知
        setTimeout(() => {
            notification.style.animation = 'slideOutUp 0.3s ease forwards';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 5000);
    }

    showLoading(show) {
        const loadingOverlay = document.getElementById('loadingOverlay');
        loadingOverlay.style.display = show ? 'flex' : 'none';
    }

    // 辅助方法
    getStatusText(status) {
        const statusMap = {
            pending: '等待中',
            running: '运行中',
            completed: '已完成',
            failed: '失败'
        };
        return statusMap[status] || status;
    }
    
    getTaskStatusIcon(status) {
        const iconMap = {
            pending: '<i class="fas fa-clock task-icon pending"></i>',
            running: '<i class="fas fa-spinner fa-spin task-icon running"></i>',
            completed: '<i class="fas fa-check-circle task-icon completed"></i>',
            failed: '<i class="fas fa-times-circle task-icon failed"></i>'
        };
        return iconMap[status] || '<i class="fas fa-question-circle task-icon"></i>';
    }

    getLogTypeText(type) {
        const typeMap = {
            workflow: '工作流',
            task: '任务',
            tool_call: '工具调用',
            framework: '框架',
            system: '系统'
        };
        return typeMap[type] || type;
    }

    getNotificationIcon(type) {
        const iconMap = {
            success: 'check-circle',
            error: 'exclamation-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };
        return iconMap[type] || 'info-circle';
    }

    formatTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    formatDuration(ms) {
        if (ms < 1000) {
            return `${Math.round(ms)}ms`;
        } else if (ms < 60000) {
            return `${(ms / 1000).toFixed(1)}s`;
        } else {
            const minutes = Math.floor(ms / 60000);
            const seconds = Math.floor((ms % 60000) / 1000);
            return `${minutes}m ${seconds}s`;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 初始化应用
const logger = new DeepGraphLogger();

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideOutUp {
        from { transform: translateY(0); opacity: 1; }
        to { transform: translateY(-100%); opacity: 0; }
    }
`;
document.head.appendChild(style);
