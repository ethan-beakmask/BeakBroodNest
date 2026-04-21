/**
 * Cell Widgets - 內嵌元件渲染器集合
 *
 * 提供：
 * - sparkline: 迷你折線圖 / 長條圖（純 SVG）
 * - riskBar: 風險指標進度條
 * - miniTree: Cell 內嵌迷你樹
 * - radioGroup: 單選按鈕組
 * - statusBadge: 狀態標籤
 *
 * 全部為工廠函式，回傳可直接作為 column.renderer 的 function
 */
'use strict';

var CellWidgets = (function() {

    // ========== Sparkline 迷你圖表 ==========

    /**
     * 建立 Sparkline 渲染器
     * @param {Object} opts
     * @param {string} [opts.type="line"] - "line"|"bar"
     * @param {string} [opts.color="#369"] - 線條/長條顏色
     * @param {string} [opts.fillColor] - 折線圖填充色（半透明）
     * @param {number} [opts.width=120] - SVG 寬度
     * @param {number} [opts.height=20] - SVG 高度
     * @param {number} [opts.strokeWidth=1.5] - 折線寬度
     * @param {number} [opts.barGap=1] - 長條間距
     * @returns {Function}
     */
    function sparkline(opts) {
        opts = Object.assign({
            type: 'line',
            color: '#369',
            fillColor: null,
            width: 120,
            height: 20,
            strokeWidth: 1.5,
            barGap: 1
        }, opts || {});

        return function(value, node, col) {
            var data = Array.isArray(value) ? value : [];
            if (data.length === 0) {
                return '<span style="color:#bbb;font-size:11px;">--</span>';
            }

            var w = opts.width;
            var h = opts.height;
            var padY = 2;

            var min = Math.min.apply(null, data);
            var max = Math.max.apply(null, data);
            var range = max - min || 1;

            var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('width', w);
            svg.setAttribute('height', h);
            svg.setAttribute('class', 'bt-sparkline');
            svg.style.verticalAlign = 'middle';

            if (opts.type === 'bar') {
                // 長條圖
                var barW = (w - (data.length - 1) * opts.barGap) / data.length;
                for (var i = 0; i < data.length; i++) {
                    var barH = ((data[i] - min) / range) * (h - padY * 2);
                    if (barH < 1) barH = 1;
                    var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                    rect.setAttribute('x', i * (barW + opts.barGap));
                    rect.setAttribute('y', h - padY - barH);
                    rect.setAttribute('width', Math.max(barW, 1));
                    rect.setAttribute('height', barH);
                    rect.setAttribute('fill', opts.color);
                    rect.setAttribute('opacity', '0.8');
                    svg.appendChild(rect);
                }
            } else {
                // 折線圖
                var points = [];
                var stepX = w / (data.length - 1 || 1);
                for (var j = 0; j < data.length; j++) {
                    var x = j * stepX;
                    var y = h - padY - ((data[j] - min) / range) * (h - padY * 2);
                    points.push(x.toFixed(1) + ',' + y.toFixed(1));
                }
                var pointsStr = points.join(' ');

                // 填充區域
                if (opts.fillColor) {
                    var fillPoints = pointsStr +
                        ' ' + w + ',' + (h - padY) +
                        ' 0,' + (h - padY);
                    var polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                    polygon.setAttribute('points', fillPoints);
                    polygon.setAttribute('fill', opts.fillColor);
                    svg.appendChild(polygon);
                }

                // 折線
                var polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
                polyline.setAttribute('points', pointsStr);
                polyline.setAttribute('fill', 'none');
                polyline.setAttribute('stroke', opts.color);
                polyline.setAttribute('stroke-width', opts.strokeWidth);
                polyline.setAttribute('stroke-linejoin', 'round');
                svg.appendChild(polyline);

                // 最後一個資料點
                if (data.length > 1) {
                    var lastX = (data.length - 1) * stepX;
                    var lastY = h - padY - ((data[data.length - 1] - min) / range) * (h - padY * 2);
                    var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                    dot.setAttribute('cx', lastX.toFixed(1));
                    dot.setAttribute('cy', lastY.toFixed(1));
                    dot.setAttribute('r', '2');
                    dot.setAttribute('fill', opts.color);
                    svg.appendChild(dot);
                }
            }

            // hover 提示
            var container = document.createElement('div');
            container.className = 'bt-sparkline-wrap';
            container.title = data.join(', ');
            container.appendChild(svg);
            return container;
        };
    }

    // ========== 風險指標進度條 ==========

    /**
     * 建立風險指標渲染器
     * @param {Object} opts
     * @param {number} [opts.max=100] - 最大值
     * @param {Array} [opts.thresholds] - 色階閾值 [{value, color, label}]
     * @param {boolean} [opts.showValue=true] - 顯示數值
     * @returns {Function}
     */
    function riskBar(opts) {
        opts = Object.assign({
            max: 100,
            thresholds: [
                { value: 30, color: '#999', label: 'LOW' },
                { value: 60, color: '#e90', label: 'MEDIUM' },
                { value: 80, color: '#e60', label: 'HIGH' },
                { value: 100, color: '#c00', label: 'CRITICAL' }
            ],
            showValue: true
        }, opts || {});

        return function(value, node, col) {
            if (value === undefined || value === null || isNaN(Number(value))) {
                return '<span style="color:#bbb;font-size:11px;">--</span>';
            }

            var num = Number(value);
            var pct = Math.min((num / opts.max) * 100, 100);

            // 找到對應色階
            var color = '#999';
            var label = '';
            for (var i = 0; i < opts.thresholds.length; i++) {
                if (num <= opts.thresholds[i].value) {
                    color = opts.thresholds[i].color;
                    label = opts.thresholds[i].label;
                    break;
                }
                color = opts.thresholds[i].color;
                label = opts.thresholds[i].label;
            }

            var container = document.createElement('div');
            container.className = 'bt-riskbar-wrap';
            container.title = num + ' / ' + opts.max + ' (' + label + ')';

            var track = document.createElement('div');
            track.className = 'bt-riskbar-track';

            var fill = document.createElement('div');
            fill.className = 'bt-riskbar-fill';
            fill.style.width = pct + '%';
            fill.style.background = color;
            track.appendChild(fill);

            container.appendChild(track);

            if (opts.showValue) {
                var text = document.createElement('span');
                text.className = 'bt-riskbar-value';
                text.style.color = color;
                text.textContent = num;
                container.appendChild(text);
            }

            return container;
        };
    }

    // ========== Cell 內嵌迷你樹 ==========

    /**
     * 建立迷你樹渲染器
     * 資料格式：[{label, children: [...]}]
     * @param {Object} opts
     * @param {number} [opts.indentPx=12] - 每層縮排像素
     * @returns {Function}
     */
    function miniTree(opts) {
        opts = Object.assign({
            indentPx: 12
        }, opts || {});

        function renderNode(node, level, isLast, prefixFlags) {
            var lines = [];
            var prefix = '';

            // 建立前綴連線
            for (var i = 0; i < prefixFlags.length; i++) {
                prefix += prefixFlags[i] ? '<span class="bt-mini-vline"></span>' : '<span class="bt-mini-blank"></span>';
            }

            var branch = '';
            if (level > 0) {
                branch = isLast
                    ? '<span class="bt-mini-last"></span>'
                    : '<span class="bt-mini-mid"></span>';
            }

            lines.push('<div class="bt-mini-row">' + prefix + branch +
                '<span class="bt-mini-label">' + (node.label || '') + '</span></div>');

            if (node.children && node.children.length > 0) {
                for (var j = 0; j < node.children.length; j++) {
                    var childIsLast = (j === node.children.length - 1);
                    var newFlags = prefixFlags.concat([!isLast && level > 0]);
                    // 根節點(level 0)不產生 prefix flag
                    if (level === 0) {
                        newFlags = prefixFlags.concat([!isLast]);
                    }
                    lines = lines.concat(renderNode(node.children[j], level + 1, childIsLast, newFlags));
                }
            }
            return lines;
        }

        return function(value, node, col) {
            var data = Array.isArray(value) ? value : [];
            if (data.length === 0) {
                return '<span style="color:#bbb;font-size:11px;">--</span>';
            }

            var html = '<div class="bt-minitree">';
            for (var i = 0; i < data.length; i++) {
                var isLast = (i === data.length - 1);
                var lines = renderNode(data[i], 0, isLast, []);
                html += lines.join('');
            }
            html += '</div>';
            return html;
        };
    }

    // ========== Radio Group ==========

    /**
     * 建立 Radio 渲染器
     * @param {Object} opts
     * @param {string} opts.name - radio group 名稱前綴
     * @param {Array} opts.options - [{value, label}]
     * @param {Function} [opts.onChange] - 變更回呼 (nodeId, selectedValue)
     * @returns {Function}
     */
    function radioGroup(opts) {
        opts = Object.assign({
            name: 'bt-radio',
            options: [],
            onChange: null
        }, opts || {});

        return function(value, node, col) {
            var container = document.createElement('div');
            container.className = 'bt-radio-group';

            for (var i = 0; i < opts.options.length; i++) {
                var opt = opts.options[i];
                var lbl = document.createElement('label');
                lbl.className = 'bt-radio-label';

                var radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = opts.name + '-' + node.id;
                radio.value = opt.value;
                radio.className = 'bt-radio-input';
                if (value === opt.value) {
                    radio.checked = true;
                }

                (function(optValue) {
                    radio.addEventListener('change', function() {
                        node.data[col.id] = optValue;
                        if (opts.onChange) {
                            opts.onChange(node.id, optValue, node);
                        }
                    });
                })(opt.value);

                lbl.appendChild(radio);
                var span = document.createElement('span');
                span.textContent = opt.label;
                lbl.appendChild(span);
                container.appendChild(lbl);
            }
            return container;
        };
    }

    // ========== Status Badge ==========

    /**
     * 建立狀態標籤渲染器
     * @param {Object} opts
     * @param {Object} opts.styles - { value: { bg, color, label } }
     * @returns {Function}
     */
    function statusBadge(opts) {
        opts = Object.assign({
            styles: {}
        }, opts || {});

        return function(value, node, col) {
            var s = opts.styles[value] || {};
            var bg = s.bg || '#f0f0f0';
            var color = s.color || '#666';
            var label = s.label || value || '--';

            return '<span class="bt-badge" style="background:' + bg +
                ';color:' + color + ';">' + label + '</span>';
        };
    }

    // ========== 公開介面 ==========

    return {
        sparkline: sparkline,
        riskBar: riskBar,
        miniTree: miniTree,
        radioGroup: radioGroup,
        statusBadge: statusBadge
    };

})();
