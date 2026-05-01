/**
 * BeakGantt v0.3 -- WBS + Custom Columns + Gantt 一體化元件
 *
 * Layout: [WBS Grid + Custom Cols | Splitter | Gantt Timeline]
 * View modes: 'both' (default), 'wbs', 'gantt'
 * Summary modes: 'summary-bar' | 'no-bar' | 'outline-only'
 *
 * Usage:
 *   var g = BeakGantt.create('#el', {
 *       data: { tasks: [...], links: [...] },
 *       customColumns: [{ key:'assignee', label:'負責人', width:80 }],
 *       customData: { 1: { assignee:'Alice' } },
 *       summaryMode: 'summary-bar',
 *       summaryBarColor: '#003366',
 *       noBarBgColor: '#DDEEFF',
 *       outlineColors: { card: '#003366', taskColors: ['#FFFFFF','#AAAAAA'] },
 *       onTaskUpdate, onTaskCreate, onLinkCreate, onLinkDelete,
 *       onTaskReorder, onCustomEdit,
 *   });
 */
'use strict';

var BeakGanttChart = (function() {

    var ROW_H = 30, DAY_MS = 864e5;
    var VM = {
        day:   { colWidth: 30 },
        week:  { colWidth: 60 },
        month: { colWidth: 80 },
    };

    // ---- utils ----
    function _pd(s) { if (!s) return null; if (s instanceof Date) return new Date(s); var d = new Date(s); return isNaN(d) ? null : d; }
    function _fd(d) { if (!d) return ''; return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'); }
    function _db(a,b) { return Math.round((b-a)/DAY_MS); }
    function _ad(d,n) { var r=new Date(d); r.setDate(r.getDate()+n); return r; }
    function _sd(d) { var r=new Date(d); r.setHours(0,0,0,0); return r; }
    function _sw(d) { var r=_sd(d),w=r.getDay(); r.setDate(r.getDate()-w+1); if(w===0) r.setDate(r.getDate()-7); return r; }
    function _sm(d) { return new Date(d.getFullYear(),d.getMonth(),1); }
    function _ml(d) { return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()]; }
    function _el(t,c,a) { var e=document.createElement(t); if(c)e.className=c; if(a){for(var k in a){if(k==='text')e.textContent=a[k];else if(k==='style')e.style.cssText=a[k];else e.setAttribute(k,a[k]);}} return e; }
    function _svg(t,a) { var e=document.createElementNS('http://www.w3.org/2000/svg',t); if(a){for(var k in a)e.setAttribute(k,a[k]);} return e; }
    function _clr(t) { if(t._status==='done') return '#198754'; if(t._urgency==='H') return '#dc2626'; if(t._urgency==='M') return '#d97706'; return '#6c757d'; }
    function _fp(p) { var v=Math.round((p||0)*100); if(v>0&&v<5)v=5; return v; }

    // ---- tree ----
    function _wbs(fl) { var c={}; for(var i=0;i<fl.length;i++){var t=fl[i],p=t.parent||0; c[p]=(c[p]||0)+1; var pr=p?fl.find(function(x){return x.id===p;}):null; t._wbs=pr&&pr._wbs?pr._wbs+'.'+c[p]:String(c[p]);} }
    function _flat(tasks) {
        var m={}; for(var i=0;i<tasks.length;i++){var t=tasks[i]; m[t.id]=t; t._children=[]; t._depth=0; if(t._expanded===undefined)t._expanded=t.open!==false; t._hasChildren=false;}
        for(var i=0;i<tasks.length;i++){var t=tasks[i],p=t.parent||0; if(p&&m[p]){m[p]._children.push(t);m[p]._hasChildren=true;}}
        var fl=[]; function w(ns,d){for(var j=0;j<ns.length;j++){ns[j]._depth=d;fl.push(ns[j]);if(ns[j]._children.length>0)w(ns[j]._children,d+1);}}
        w(tasks.filter(function(t){return !t.parent||t.parent===0||!m[t.parent];}),0);
        _wbs(fl); return fl;
    }
    function _vis(fl) {
        var v=[],col={}; for(var i=0;i<fl.length;i++){var t=fl[i],h=false,p=t.parent||0;
        while(p&&!h){if(col[p]){h=true;break;}var pr=fl.find(function(x){return x.id===p;});p=pr?(pr.parent||0):0;}
        if(h)continue; v.push(t); if(t._hasChildren&&!t._expanded)col[t.id]=true;} return v;
    }

    // ---- summary date auto-calc ----
    function _calcSummaryDates(flatList) {
        for (var i = flatList.length - 1; i >= 0; i--) {
            var t = flatList[i];
            if (!t._isSummary || !t._hasChildren) continue;
            var minS = null, maxE = null;
            for (var j = 0; j < t._children.length; j++) {
                var c = t._children[j];
                var cs = _pd(c.start_date) || c._calcStart;
                var ce = _pd(c.end_date) || c._calcEnd;
                if (!ce && cs && c.duration) ce = _ad(cs, c.duration);
                if (cs && (!minS || cs < minS)) minS = cs;
                if (ce && (!maxE || ce > maxE)) maxE = ce;
            }
            if (minS) t._calcStart = minS;
            if (maxE) t._calcEnd = maxE;
            if (minS && maxE) t._calcDuration = _db(minS, maxE);
        }
    }

    // ---- time range ----
    function _tr(tasks) {
        var mn=null,mx=null;
        for(var i=0;i<tasks.length;i++){var t=tasks[i],s=_pd(t.start_date)||t._calcStart,e=_pd(t.end_date)||t._calcEnd;if(!e&&s&&t.duration)e=_ad(s,t.duration);
        if(s){if(!mn||s<mn)mn=s;if(!mx||s>mx)mx=s;}if(e){if(!mn||e<mn)mn=e;if(!mx||e>mx)mx=e;}}
        if(!mn)mn=new Date();if(!mx)mx=_ad(mn,30);
        return{start:_ad(_sd(mn),-3),end:_ad(_sd(mx),10)};
    }
    function _d2x(d,rs,cw,vm){if(!d)return null;if(vm==='day')return _db(rs,d)*cw;if(vm==='week')return(_db(rs,d)/7)*cw;if(vm==='month'){var m=(d.getFullYear()-rs.getFullYear())*12+(d.getMonth()-rs.getMonth())+(d.getDate()-1)/30;return m*cw;}return 0;}
    function _x2d(x,rs,cw,vm){if(vm==='day')return _ad(rs,Math.round(x/cw));if(vm==='week')return _ad(rs,Math.round((x/cw)*7));if(vm==='month'){var m=x/cw;var d=new Date(rs);d.setMonth(d.getMonth()+Math.floor(m));d.setDate(d.getDate()+Math.round((m%1)*30));return d;}return rs;}

    // ---- scale ----
    function _scale(con,rng,vm) {
        con.innerHTML=''; var cw=VM[vm].colWidth;
        var tr=_el('div','bk-scale-row'),br=_el('div','bk-scale-row');
        if(vm==='day'){var c=new Date(rng.start),pm=-1,ms=0,mc=[],di=0;while(c<=rng.end){var dc=_el('div','bk-scale-cell',{text:String(c.getDate()),style:'width:'+cw+'px;'});var dw=c.getDay();if(dw===0||dw===6)dc.style.background='#f8f0f0';br.appendChild(dc);var m=c.getMonth();if(m!==pm){if(pm!==-1)mc.push({l:_ml(new Date(c.getFullYear(),pm,1))+' '+c.getFullYear(),w:(di-ms)*cw});ms=di;pm=m;}di++;c=_ad(c,1);}if(pm!==-1)mc.push({l:_ml(new Date(rng.end.getFullYear(),pm,1))+' '+rng.end.getFullYear(),w:(di-ms)*cw});for(var i=0;i<mc.length;i++)tr.appendChild(_el('div','bk-scale-cell',{text:mc[i].l,style:'width:'+mc[i].w+'px;'}));}
        else if(vm==='week'){var c=_sw(rng.start),pm=-1,ms=0,wi=0,mc=[];while(c<=rng.end){var we=_ad(c,6);br.appendChild(_el('div','bk-scale-cell',{text:c.getDate()+'-'+we.getDate(),style:'width:'+cw+'px;'}));var m=c.getMonth();if(m!==pm){if(pm!==-1)mc.push({l:_ml(new Date(c.getFullYear(),pm,1))+' '+c.getFullYear(),w:(wi-ms)*cw});ms=wi;pm=m;}wi++;c=_ad(c,7);}if(pm!==-1)mc.push({l:_ml(new Date(rng.end.getFullYear(),pm,1))+' '+rng.end.getFullYear(),w:(wi-ms)*cw});for(var i=0;i<mc.length;i++)tr.appendChild(_el('div','bk-scale-cell',{text:mc[i].l,style:'width:'+mc[i].w+'px;'}));}
        else if(vm==='month'){var c=_sm(rng.start),py=-1,ys=0,mi=0,yc=[];while(c<=rng.end){br.appendChild(_el('div','bk-scale-cell',{text:_ml(c),style:'width:'+cw+'px;'}));var y=c.getFullYear();if(y!==py){if(py!==-1)yc.push({l:String(py),w:(mi-ys)*cw});ys=mi;py=y;}mi++;c=new Date(c.getFullYear(),c.getMonth()+1,1);}if(py!==-1)yc.push({l:String(py),w:(mi-ys)*cw});for(var i=0;i<yc.length;i++)tr.appendChild(_el('div','bk-scale-cell',{text:yc[i].l,style:'width:'+yc[i].w+'px;'}));}
        con.appendChild(tr);con.appendChild(br);
    }

    // ============================================================
    // 主類別
    // ============================================================

    function G(con, opts) {
        this._container = typeof con==='string'?document.querySelector(con):con;
        this._opts = Object.assign({
            gridWidth:450, viewMode:'day',
            customColumns:[], customData:{},
            summaryMode: 'summary-bar',
            summaryBarColor: '#266ACF',
            noBarBgColor: '#3A9CFD',
            outlineColors: { card: '#3A9CFD', taskColors: ['#F0F0FF', '#F7FFF5', '#F0F9FF'] },
            onTaskUpdate:null, onTaskCreate:null, onTaskDelete:null,
            onLinkCreate:null, onLinkDelete:null,
            onTaskReorder:null, onCustomEdit:null,
        }, opts||{});
        this._tasks=[]; this._links=[];
        this._flatList=[]; this._visibleList=[];
        this._timeRange=null; this._viewMode=this._opts.viewMode;
        this._layout='both';
        this._gridEl=null; this._timelineEl=null; this._splitterEl=null;
        this._scaleEl=null; this._rowsEl=null; this._depsEl=null;
        this._barEls={}; this._linkLine=null;
        this._undoStack=[];
        this._init();
    }
    var P=G.prototype;

    P._init = function() {
        var r=this._container; r.innerHTML=''; r.classList.add('bk-gantt');
        this._gridEl=_el('div','bk-gantt-grid'); this._gridEl.style.width=this._opts.gridWidth+'px';
        r.appendChild(this._gridEl);
        this._splitterEl=_el('div','bk-gantt-splitter'); r.appendChild(this._splitterEl); this._initSplitter();
        this._timelineEl=_el('div','bk-gantt-timeline'); r.appendChild(this._timelineEl);
        this._scaleEl=_el('div','bk-gantt-scale'); this._timelineEl.appendChild(this._scaleEl);
        this._rowsEl=_el('div','bk-gantt-rows'); this._timelineEl.appendChild(this._rowsEl);
        this._depsEl=_svg('svg',{'class':'bk-gantt-deps'}); this._rowsEl.appendChild(this._depsEl);
        this._initScrollSync();
    };

    P._initSplitter = function() {
        var self=this,sx,sw;
        var mv=function(e){var maxW=self._container.offsetWidth-50; self._gridEl.style.width=Math.max(50,Math.min(maxW,sw+(e.clientX-sx)))+'px';};
        var up=function(){self._splitterEl.classList.remove('dragging');document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);};
        this._splitterEl.addEventListener('mousedown',function(e){e.preventDefault();sx=e.clientX;sw=self._gridEl.offsetWidth;self._splitterEl.classList.add('dragging');document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);});
    };

    P._initScrollSync = function() {
        var g=this._gridEl,t=this._timelineEl,s=false;
        g.addEventListener('scroll',function(){if(!s){s=true;t.scrollTop=g.scrollTop;s=false;}});
        t.addEventListener('scroll',function(){if(!s){s=true;g.scrollTop=t.scrollTop;s=false;}});
    };

    P.parse = function(d) {
        this._tasks=(d.tasks||d.data||[]).map(function(t){return Object.assign({},t);});
        this._links=(d.links||[]).map(function(l){return Object.assign({},l);});
        this.render();
    };
    P.clearAll = function(){this._tasks=[];this._links=[];this._flatList=[];this._visibleList=[];this._gridEl.innerHTML='';this._rowsEl.innerHTML='';this._scaleEl.innerHTML='';};

    P.render = function() {
        this._flatList=_flat(this._tasks);
        _calcSummaryDates(this._flatList);
        this._visibleList=_vis(this._flatList);
        this._timeRange=_tr(this._tasks);
        this._barEls={};
        this._renderGrid();
        this._renderTimeline();
        this._renderDeps();
        this._syncH();
    };

    // ---- Layout switching ----
    P.setLayout = function(mode) {
        if (this._layout === mode) return;
        this._layout = mode;
        if (mode === 'wbs') {
            this._gridEl.style.display = '';  this._gridEl.style.flex = '1';  this._gridEl.style.width = '';
            this._splitterEl.style.display = 'none';  this._timelineEl.style.display = 'none';
        } else if (mode === 'gantt') {
            this._gridEl.style.display = 'none';  this._splitterEl.style.display = 'none';
            this._timelineEl.style.display = '';  this._timelineEl.style.flex = '1';
        } else {
            this._gridEl.style.display = '';  this._gridEl.style.flex = '';
            this._gridEl.style.width = this._opts.gridWidth + 'px';
            this._splitterEl.style.display = '';  this._timelineEl.style.display = '';
            this._timelineEl.style.flex = '1';
        }
        this.render();
    };

    // ---- height sync ----
    P._syncH = function() {
        var th=this._gridEl.querySelector('thead'),sc=this._scaleEl;
        if(th&&sc&&this._layout!=='wbs'&&this._layout!=='gantt'){th.style.height='';var shh=sc.offsetHeight,thh=th.offsetHeight,mh=Math.max(shh,thh);th.querySelector('tr').style.height=mh+'px';sc.style.height=mh+'px';}
        var gr=this._gridEl.querySelectorAll('tbody tr:not(.bk-drop-zone-row)');
        var tr=this._rowsEl.querySelectorAll('.bk-gantt-row:not(.bk-drop-zone-timeline)');
        var len=Math.min(gr.length,tr.length);
        for(var i=0;i<len;i++){gr[i].style.height='';tr[i].style.height='';}
        for(var i=0;i<len;i++){var h=Math.max(gr[i].offsetHeight,tr[i].offsetHeight,ROW_H);gr[i].style.height=h+'px';tr[i].style.height=h+'px';}
        var tH=0;for(var i=0;i<len;i++)tH+=parseInt(tr[i].style.height);
        this._rowsEl.style.height=tH+ROW_H+'px';
        this._depsEl.setAttribute('height',tH+ROW_H);
    };

    // ---- outline/no-bar row background ----
    function _rowBgColor(task, taskIdx, opts) {
        var mode = opts.summaryMode;
        var oc = opts.outlineColors || {};
        if (mode === 'outline-only') {
            if (task._isSummary) return oc.card || '#003366';
            var colors = oc.taskColors || ['#FFFFFF', '#AAAAAA'];
            return colors[taskIdx % colors.length];
        }
        if (mode === 'no-bar' && task._isSummary) return opts.noBarBgColor || '#DDEEFF';
        return '';
    }

    // ---- WBS Grid (left) ----
    P._renderGrid = function() {
        var self=this; this._gridEl.innerHTML='';
        var tbl=_el('table'),thd=_el('thead'),htr=_el('tr');
        var cols=[
            {k:'grip',l:'',w:18},{k:'add',l:'',w:22},{k:'del',l:'',w:22},
            {k:'wbs',l:'WBS',w:46},{k:'text',l:'項目',w:155},
            {k:'start',l:'開始',w:78},{k:'dur',l:'天',w:30},{k:'progress',l:'進度',w:78},
            {k:'urgency',l:'急',w:28},{k:'status',l:'狀態',w:52},
        ];
        var ccols=this._opts.customColumns||[];
        var customStartIdx=cols.length;
        for(var ci=0;ci<ccols.length;ci++) cols.push({k:'_c_'+ccols[ci].key,l:ccols[ci].label,w:ccols[ci].width||80,custom:ccols[ci]});

        for(var i=0;i<cols.length;i++){
            var thCls=(i===customStartIdx&&ccols.length>0)?'bk-th-sep':'';
            htr.appendChild(_el('th',thCls,{text:cols[i].l,style:'width:'+cols[i].w+'px;'}));
        }
        thd.appendChild(htr); tbl.appendChild(thd);

        var taskColorIdx=0;
        var tb=_el('tbody');
        for(var r=0;r<this._visibleList.length;r++){
            var task=this._visibleList[r],row=_el('tr');
            row.dataset.taskId=task.id;
            if(task._status==='done') row.className='bk-row-done';
            var isSummary=!!task._isSummary;
            if(isSummary){row.classList.add('bk-row-summary');taskColorIdx=0;}
            var bgColor=_rowBgColor(task,isSummary?0:taskColorIdx,this._opts);
            if(bgColor){row.style.setProperty('--bk-row-bg',bgColor);row.classList.add('bk-row-colored');}
            if(!isSummary) taskColorIdx++;

            for(var ci=0;ci<cols.length;ci++){
                var col=cols[ci],td;
                switch(col.k){
                case 'grip':
                    td=_el('td','bk-grip',{text:'\u2630'});
                    if(!isSummary)this._initRowDrag(td,task,r);
                    break;
                case 'wbs':
                    td=_el('td','bk-wbs-num',{text:task._wbs||''});break;
                case 'text':
                    td=_el('td');
                    var div=_el('div','bk-tree-cell');
                    for(var d=0;d<task._depth;d++)div.appendChild(_el('span','bk-tree-indent'));
                    var tg=_el('span',task._hasChildren?'bk-tree-toggle':'bk-tree-toggle bk-tree-leaf',{text:task._hasChildren?(task._expanded?'\u25BC':'\u25B6'):'\u2022'});
                    if(task._hasChildren)(function(t){tg.addEventListener('click',function(){t._expanded=!t._expanded;self.render();});})(task);
                    div.appendChild(tg);
                    var ts=_el('span','bk-tree-text',{text:task.text||''});
                    if(isSummary)ts.style.fontWeight='700';
                    div.appendChild(ts);td.appendChild(div);break;
                case 'start':
                    var sd=isSummary?task._calcStart:_pd(task.start_date);
                    td=_el('td','',{text:sd?_fd(sd):'',style:'text-align:center;font-variant-numeric:tabular-nums;'});break;
                case 'dur':
                    var dur='';
                    if(isSummary&&task._calcDuration)dur=task._calcDuration;
                    else{dur=task.duration||'';if(!dur&&task.start_date&&task.end_date){var ss=_pd(task.start_date),ee=_pd(task.end_date);if(ss&&ee)dur=_db(ss,ee);}}
                    td=_el('td','',{text:String(dur||''),style:'text-align:center;'});break;
                case 'progress':
                    td=_el('td');var pct=_fp(task.progress),pv=_el('div','bk-progress-cell'),pb=_el('div','bk-progress-bar');
                    pb.appendChild(_el('div','bk-progress-fill',{style:'width:'+pct+'%;background:'+_clr(task)+';'}));
                    pv.appendChild(pb);pv.appendChild(_el('span','bk-progress-text',{text:pct+'%'}));td.appendChild(pv);break;
                case 'urgency':
                    td=_el('td','',{style:'text-align:center;'});
                    if(task._urgency)td.appendChild(_el('span','bk-badge bk-badge-'+task._urgency,{text:task._urgency}));break;
                case 'status':
                    td=_el('td','',{style:'text-align:center;'});
                    var sm={pending:'Pending',in_progress:'Working',done:'Done'};
                    if(task._status)td.appendChild(_el('span','bk-badge bk-badge-'+task._status,{text:sm[task._status]||task._status}));break;
                case 'add':
                    td=_el('td','',{style:'text-align:center;'});
                    var ab=_el('span','bk-add-btn',{text:'+'});
                    (function(t){ab.addEventListener('click',function(){if(self._opts.onTaskCreate)self._opts.onTaskCreate(t.id);});})(task);
                    td.appendChild(ab);break;
                case 'del':
                    td=_el('td','',{style:'text-align:center;'});
                    var delb=_el('span','bk-del-btn',{text:'\u2212'});
                    (function(t){delb.addEventListener('click',function(){
                        if(!confirm('Delete "'+t.text+'"?'))return;
                        var idx=self._tasks.indexOf(t);if(idx>=0)self._tasks.splice(idx,1);
                        var removeIds=[t.id],found=true;
                        while(found){found=false;for(var j=self._tasks.length-1;j>=0;j--){if(removeIds.indexOf(self._tasks[j].parent)>=0){removeIds.push(self._tasks[j].id);self._tasks.splice(j,1);found=true;}}}
                        for(var j=self._links.length-1;j>=0;j--){if(removeIds.indexOf(self._links[j].source)>=0||removeIds.indexOf(self._links[j].target)>=0)self._links.splice(j,1);}
                        if(self._opts.onTaskDelete)self._opts.onTaskDelete(t.id,removeIds);
                        self.render();
                    });})(task);
                    td.appendChild(delb);break;
                default:
                    if(col.custom){
                        var cd=self._opts.customData[task.id]||{},val=cd[col.custom.key]||'';
                        td=_el('td','bk-custom-cell',{text:String(val),style:'text-align:'+(col.custom.align||'left')+';cursor:pointer;'});
                        td.title='click to edit';
                        (function(t){td.addEventListener('click',function(){if(self._opts.onCustomEdit)self._opts.onCustomEdit(t.id,self._opts.customData[t.id]||{});});})(task);
                    } else td=_el('td');
                }
                if(ci===customStartIdx&&ccols.length>0)td.classList.add('bk-td-sep');
                row.appendChild(td);
            }
            tb.appendChild(row);
        }
        var dzr=_el('tr','bk-drop-zone-row'),dzt=_el('td','bk-drop-zone',{style:'text-align:center;color:#aaa;font-size:10px;border-top:2px dashed #ccc;'});
        dzt.setAttribute('colspan',String(cols.length));dzt.textContent='-- drop here to make root --';
        dzr.appendChild(dzt);tb.appendChild(dzr);
        tbl.appendChild(tb);this._gridEl.appendChild(tbl);
    };

    // ---- Row drag ----
    P._initRowDrag = function(el,task,ri) {
        var self=this;
        el.addEventListener('mousedown',function(e){
            e.preventDefault();
            var gr=self._gridEl.getBoundingClientRect();
            var rows=self._gridEl.querySelectorAll('tbody tr:not(.bk-drop-zone-row)'),cnt=rows.length;
            var gh=_el('div','',{text:task.text,style:'position:fixed;left:'+gr.left+'px;padding:4px 8px;background:#3b82f6;color:#fff;font-size:12px;border-radius:3px;z-index:9999;pointer-events:none;opacity:0.9;'});
            document.body.appendChild(gh);
            var ind=_el('div','',{style:'position:absolute;left:0;right:0;height:2px;background:#3b82f6;z-index:100;pointer-events:none;display:none;'});
            self._gridEl.style.position='relative';self._gridEl.appendChild(ind);
            var di=-1,dz=false;
            var mv=function(ev){
                gh.style.top=(ev.clientY-10)+'px';
                var y=ev.clientY-gr.top+self._gridEl.scrollTop;
                var thH=self._gridEl.querySelector('thead')?self._gridEl.querySelector('thead').offsetHeight:0;
                y-=thH;var idx=0,cH=0;dz=false;
                for(var i=0;i<cnt;i++){var rh=rows[i].offsetHeight;if(y<cH+rh/2){idx=i;break;}cH+=rh;idx=i+1;}
                if(idx>=cnt){dz=true;idx=cnt;}
                di=idx;var iy=thH;
                for(var i=0;i<idx&&i<cnt;i++)iy+=rows[i].offsetHeight;
                ind.style.display='';ind.style.top=iy+'px';ind.style.background=dz?'#dc2626':'#3b82f6';
            };
            var up=function(){
                document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);
                gh.remove();ind.remove();
                if(di<0||(!dz&&(di===ri||di===ri+1)))return;
                var np=dz?0:(di<self._visibleList.length?(self._visibleList[di].parent||0):(di>0?(self._visibleList[di-1].parent||0):0));
                var checkId=np;
                while(checkId&&checkId!==0){if(checkId===task.id)return;var cp=self._tasks.find(function(x){return x.id===checkId;});checkId=cp?(cp.parent||0):0;}
                task.parent=np;
                var ti=self._tasks.indexOf(task);if(ti>=0)self._tasks.splice(ti,1);
                if(dz){self._tasks.push(task);}else{var tt=di<self._visibleList.length?self._visibleList[di]:null;var ib=tt?self._tasks.indexOf(tt):self._tasks.length;if(ib<0)ib=self._tasks.length;self._tasks.splice(ib,0,task);}
                if(self._opts.onTaskReorder)self._opts.onTaskReorder(task.id,np,di);
                self.render();
            };
            document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
        });
    };

    // ---- Timeline (right) ----
    P._renderTimeline = function() {
        var cw=VM[this._viewMode].colWidth,rng=this._timeRange;
        _scale(this._scaleEl,rng,this._viewMode);
        var td=_db(rng.start,rng.end),tw;
        if(this._viewMode==='day')tw=td*cw;else if(this._viewMode==='week')tw=Math.ceil(td/7)*cw;
        else{var m=(rng.end.getFullYear()-rng.start.getFullYear())*12+rng.end.getMonth()-rng.start.getMonth()+1;tw=m*cw;}

        this._rowsEl.innerHTML='';this._rowsEl.style.width=tw+'px';
        this._rowsEl.style.height=(this._visibleList.length*ROW_H+ROW_H)+'px';
        this._depsEl=_svg('svg',{'class':'bk-gantt-deps',width:tw,height:this._visibleList.length*ROW_H+ROW_H});
        this._rowsEl.appendChild(this._depsEl);
        this._linkLine=_svg('line',{'class':'bk-link-temp',x1:0,y1:0,x2:0,y2:0,style:'display:none'});
        this._depsEl.appendChild(this._linkLine);

        var tx=_d2x(_sd(new Date()),rng.start,cw,this._viewMode);
        if(tx>0&&tx<tw)this._rowsEl.appendChild(_el('div','bk-today-line',{style:'left:'+tx+'px;'}));

        var self=this,sMode=this._opts.summaryMode,taskColorIdx=0;

        for(var r=0;r<this._visibleList.length;r++){
            var task=this._visibleList[r],isSummary=!!task._isSummary;
            var rd=_el('div','bk-gantt-row');
            if(isSummary){rd.classList.add('bk-row-summary');taskColorIdx=0;}

            var bgColor=_rowBgColor(task,isSummary?0:taskColorIdx,this._opts);
            if(bgColor){rd.style.background=bgColor;rd.classList.add('bk-row-colored');
                if(sMode==='outline-only'&&isSummary)rd.style.color='#fff';}
            if(!isSummary)taskColorIdx++;

            var renderBar=true,s,e;
            if(isSummary){
                if(sMode==='summary-bar'){s=task._calcStart||null;e=task._calcEnd||null;}
                else{renderBar=false;s=null;e=null;}
            }else{s=_pd(task.start_date);e=_pd(task.end_date);if(!e&&s&&task.duration)e=_ad(s,task.duration);}

            if(renderBar&&s){
                var x1=_d2x(s,rng.start,cw,this._viewMode),x2=e?_d2x(e,rng.start,cw,this._viewMode):x1+cw*3;
                var bw=Math.max(4,x2-x1);

                if(isSummary&&sMode==='summary-bar'){
                    var sbc=this._opts.summaryBarColor||'#003366';
                    var bar=_el('div','bk-bar bk-bar-summary',{style:'left:'+x1+'px;width:'+bw+'px;'});
                    bar.dataset.taskId=task.id;bar._task=task;bar._rowIdx=r;
                    this._barEls[task.id]=bar;
                    var body=_el('div','bk-bar-body');body.style.background=sbc;body.style.borderColor=sbc;bar.appendChild(body);
                    var capL=_el('div','bk-bar-summary-cap bk-bar-summary-cap-l');capL.style.borderTopColor=sbc;bar.appendChild(capL);
                    var capR=_el('div','bk-bar-summary-cap bk-bar-summary-cap-r');capR.style.borderTopColor=sbc;bar.appendChild(capR);
                    bar.appendChild(_el('div','bk-bar-text',{text:task.text||''}));
                    bar.title=task._wbs+'  '+task.text+'\nSpan: '+_fd(s)+' ~ '+_fd(e);
                    rd.appendChild(bar);
                }else{
                    var uc=task._status==='done'?'bk-bar-done':'bk-bar-'+(task._urgency||'L');
                    var bar=_el('div','bk-bar '+uc,{style:'left:'+x1+'px;width:'+bw+'px;'});
                    bar.dataset.taskId=task.id;bar._task=task;bar._rowIdx=r;
                    this._barEls[task.id]=bar;
                    bar.appendChild(_el('div','bk-bar-body'));
                    var pw=Math.round(bw*(task.progress||0));
                    var pd=_el('div','bk-bar-progress',{style:'width:'+pw+'px;'});bar.appendChild(pd);
                    var hl=Math.min(pw,bw-10)-4;if(hl<0)hl=0;
                    var ph=_el('div','bk-bar-progress-handle',{style:'left:'+hl+'px;'});bar.appendChild(ph);
                    bar.appendChild(_el('div','bk-bar-text',{text:task.text||''}));
                    bar.appendChild(_el('div','bk-bar-resize'));
                    var stM={pending:'Pending',in_progress:'Working',done:'Done'};
                    bar.title=[task._wbs+'  '+task.text,'Start: '+(task.start_date||'-')+'  End: '+(task.end_date||'-'),'Progress: '+_fp(task.progress)+'%  Urgency: '+(task._urgency||'-')+'  Status: '+(stM[task._status]||'-')].join('\n');
                    var ld=_el('div','bk-link-dot bk-link-dot-right');bar.appendChild(ld);
                    this._initLinkDrag(ld,task,r);
                    this._initBarDrag(bar,task,rng,cw);
                    this._initBarResize(bar,task,rng,cw);
                    this._initProgressDrag(bar,pd,ph,task,bw);
                    rd.appendChild(bar);
                }
            }else if(isSummary&&(sMode==='no-bar'||sMode==='outline-only')){
                var label=_el('div','bk-summary-label',{text:task.text||'',
                    style:'padding:0 8px;line-height:'+ROW_H+'px;font-weight:700;font-size:11px;'
                        +(sMode==='outline-only'?'color:#fff;':'color:#003366;')});
                rd.appendChild(label);
            }

            this._rowsEl.appendChild(rd);
        }
        this._rowsEl.appendChild(_el('div','bk-gantt-row bk-drop-zone-timeline',{style:'border-top:2px dashed #ccc;'}));
    };

    // ---- bar drag (move) ----
    P._initBarDrag = function(bar,task,rng,cw) {
        var self=this;
        bar.addEventListener('mousedown',function(e){
            if(e.target.classList.contains('bk-bar-resize')||e.target.classList.contains('bk-bar-progress-handle')||e.target.classList.contains('bk-link-dot'))return;
            e.preventDefault();var sx=e.clientX,ol=parseInt(bar.style.left),ow=parseInt(bar.style.width);
            var mv=function(ev){var nl=ol+(ev.clientX-sx);bar.style.left=nl+'px';task.start_date=_fd(_x2d(nl,rng.start,cw,self._viewMode));task.end_date=_fd(_x2d(nl+ow,rng.start,cw,self._viewMode));self._renderDeps();};
            var up=function(){document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);if(self._opts.onTaskUpdate)self._opts.onTaskUpdate(task,{start_date:task.start_date,end_date:task.end_date});self.render();};
            document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
        });
    };

    // ---- bar resize ----
    P._initBarResize = function(bar,task,rng,cw) {
        var self=this,re=bar.querySelector('.bk-bar-resize');if(!re)return;
        re.addEventListener('mousedown',function(e){
            e.preventDefault();e.stopPropagation();var sx=e.clientX,ow=parseInt(bar.style.width),ol=parseInt(bar.style.left);
            var mv=function(ev){var nw=Math.max(4,ow+(ev.clientX-sx));bar.style.width=nw+'px';task.end_date=_fd(_x2d(ol+nw,rng.start,cw,self._viewMode));self._renderDeps();};
            var up=function(){document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);var nw=parseInt(bar.style.width);task.end_date=_fd(_x2d(ol+nw,rng.start,cw,self._viewMode));if(task.start_date&&task.end_date)task.duration=_db(_pd(task.start_date),_pd(task.end_date));if(self._opts.onTaskUpdate)self._opts.onTaskUpdate(task,{end_date:task.end_date});self.render();};
            document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
        });
    };

    // ---- progress drag ----
    P._initProgressDrag = function(bar,pd,ph,task,bw) {
        var self=this;
        ph.addEventListener('mousedown',function(e){
            e.preventDefault();e.stopPropagation();var sx=e.clientX,opw=parseInt(pd.style.width)||0;
            var mv=function(ev){var nw=Math.max(0,Math.min(bw,opw+(ev.clientX-sx)));pd.style.width=nw+'px';var hl=Math.min(nw,bw-10)-4;if(hl<0)hl=0;ph.style.left=hl+'px';};
            var up=function(){document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);var nw=parseInt(pd.style.width)||0;task.progress=Math.max(0,Math.min(1,Math.round(nw/bw*100)/100));if(task.progress>=1)task._status='done';else if(task.progress>0)task._status='in_progress';else task._status='pending';if(self._opts.onTaskUpdate)self._opts.onTaskUpdate(task,{progress:task.progress,_status:task._status});self.render();};
            document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
        });
    };

    // ---- link drag (create) ----
    P._initLinkDrag = function(dot,src,ri) {
        var self=this;
        dot.addEventListener('mousedown',function(e){
            e.preventDefault();e.stopPropagation();
            var sb=self._barEls[src.id];
            var trs=self._rowsEl.querySelectorAll('.bk-gantt-row:not(.bk-drop-zone-timeline)');
            var rr=self._rowsEl.getBoundingClientRect();
            var sbRect=sb.getBoundingClientRect();
            var x1=sbRect.right-rr.left;
            var y1=sbRect.top+sbRect.height/2-rr.top;
            self._linkLine.style.display='';self._linkLine.setAttribute('x1',x1);self._linkLine.setAttribute('y1',y1);
            self._linkLine.setAttribute('x2',x1);self._linkLine.setAttribute('y2',y1);
            var mv=function(ev){var rr2=self._rowsEl.getBoundingClientRect();self._linkLine.setAttribute('x2',ev.clientX-rr2.left);self._linkLine.setAttribute('y2',ev.clientY-rr2.top);};
            var up=function(ev){
                document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);self._linkLine.style.display='none';
                self._linkLine.setAttribute('x2',x1);self._linkLine.setAttribute('y2',y1);
                var elUnder=document.elementFromPoint(ev.clientX,ev.clientY);
                var barEl=elUnder?elUnder.closest('.bk-bar[data-task-id]'):null;
                if(!barEl)return;
                var tgtId=barEl.dataset.taskId;
                if(tgtId==String(src.id))return;
                var tgt=self._visibleList.find(function(x){return String(x.id)===String(tgtId);});
                if(!tgt)return;
                var nl={id:'l_'+src.id+'_'+tgt.id,source:src.id,target:tgt.id,type:'0'};
                self._links.push(nl);self._undoStack=[{type:'link_create',link:nl}];
                if(self._opts.onLinkCreate)self._opts.onLinkCreate(src.id,tgt.id);self._renderDeps();
            };
            document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
        });
    };

    // ---- deps rendering ----
    P._renderDeps = function() {
        var ch=this._depsEl.children;
        for(var i=ch.length-1;i>=0;i--){if(ch[i]!==this._linkLine)this._depsEl.removeChild(ch[i]);}
        var cw=VM[this._viewMode].colWidth,rng=this._timeRange;
        var idx={},ry=[],trs=this._rowsEl.querySelectorAll('.bk-gantt-row:not(.bk-drop-zone-timeline)'),cy=0;
        for(var i=0;i<this._visibleList.length;i++){idx[this._visibleList[i].id]=i;var rh=ROW_H;if(trs[i])rh=parseInt(trs[i].style.height)||ROW_H;ry.push(cy+rh/2);cy+=rh;}

        var self=this;
        for(var i=0;i<this._links.length;i++){
            var lk=this._links[i],si=idx[lk.source],ti=idx[lk.target];
            if(si===undefined||ti===undefined)continue;
            var st=this._visibleList[si],tt=this._visibleList[ti];
            var sb=this._barEls[st.id],tb=this._barEls[tt.id];
            var x1,x2;
            if(sb){x1=parseInt(sb.style.left)+parseInt(sb.style.width);}
            else{var se=_pd(st.end_date);if(!se&&st.start_date&&st.duration)se=_ad(_pd(st.start_date),st.duration);if(!se&&st._calcEnd)se=st._calcEnd;if(!se)continue;x1=_d2x(se,rng.start,cw,this._viewMode);}
            if(tb){x2=parseInt(tb.style.left);}
            else{var ts=_pd(tt.start_date);if(!ts&&tt._calcStart)ts=tt._calcStart;if(!ts)continue;x2=_d2x(ts,rng.start,cw,this._viewMode);}
            var y1=ry[si],y2=ry[ti];
            var gap=x2-x1;
            var srb,trt,cH2=0,rowEdges=[0];
            for(var ri=0;ri<=Math.max(si,ti);ri++){var rh=ROW_H;if(trs[ri])rh=parseInt(trs[ri].style.height)||ROW_H;if(ri===si)srb=cH2+rh;if(ri===ti)trt=cH2;cH2+=rh;rowEdges.push(cH2);}
            var path;
            if(si===ti){
                var hg0=gap>0?Math.min(12,gap/2):12;
                var ym0=y1-ROW_H/2-5;
                path='M'+x1+','+y1+' H'+(x1+hg0)+' V'+ym0+' H'+(x2-hg0)+' V'+y2+' H'+x2;
            }else if(gap>=0&&gap<=24){
                path='M'+x1+','+y1+' V'+y2+' H'+x2;
            }else{
                var hg=gap>0?Math.min(12,gap/2):12;
                var top=Math.min(srb,trt),bot=Math.max(srb,trt);
                var rawYm=(top+bot)/2,ym=rawYm,bestDist=Infinity;
                for(var k=0;k<rowEdges.length;k++){var ed=rowEdges[k];if(ed>=top&&ed<=bot){var dist=Math.abs(ed-rawYm);if(dist<bestDist){bestDist=dist;ym=ed;}}}
                path='M'+x1+','+y1+' H'+(x1+hg)+' V'+ym+' H'+(x2-hg)+' V'+y2+' H'+x2;
            }
            var lineEl=_svg('path',{d:path,'class':'bk-dep-line'});
            var arrowEl=_svg('polygon',{points:(x2-5)+','+(y2-4)+' '+x2+','+y2+' '+(x2-5)+','+(y2+4),'class':'bk-dep-arrow'});
            var hit=_svg('path',{d:path,'class':'bk-dep-hit',fill:'none',stroke:'transparent','stroke-width':'12','pointer-events':'stroke',style:'cursor:pointer'});
            hit.setAttribute('data-link-idx',i);
            (function(linkIdx,lnk,lEl,aEl){
                hit.addEventListener('mouseenter',function(){lEl.classList.add('bk-dep-hl');aEl.classList.add('bk-dep-hl');});
                hit.addEventListener('mouseleave',function(){lEl.classList.remove('bk-dep-hl');aEl.classList.remove('bk-dep-hl');});
                hit.addEventListener('click',function(ev){
                    ev.stopPropagation();if(!confirm('Delete dependency: #'+lnk.source+' -> #'+lnk.target+'?'))return;
                    self._undoStack=[{type:'link_delete',link:lnk,index:linkIdx}];self._links.splice(linkIdx,1);
                    if(self._opts.onLinkDelete)self._opts.onLinkDelete(lnk.source,lnk.target);self._renderDeps();
                });
            })(i,lk,lineEl,arrowEl);
            this._depsEl.appendChild(lineEl);
            this._depsEl.appendChild(arrowEl);
            this._depsEl.appendChild(hit);
        }
    };

    // ---- Undo ----
    P.undo = function() {
        if(!this._undoStack.length)return null;
        var item=this._undoStack.pop();
        if(item.type==='link_create'){var idx=this._links.indexOf(item.link);if(idx>=0)this._links.splice(idx,1);this._renderDeps();return{type:'link_undo_create'};}
        if(item.type==='link_delete'){this._links.splice(item.index,0,item.link);this._renderDeps();return{type:'link_undo_delete'};}
        if(item.type==='task')return{type:'task',taskId:item.taskId,oldValues:item.oldValues};
        return null;
    };
    P.pushUndo = function(item){this._undoStack=[item];};
    P.hasUndo = function(){return this._undoStack.length>0;};

    // ---- public API ----
    P.setViewMode = function(m){if(VM[m]&&this._viewMode!==m){this._viewMode=m;this.render();}};
    P.setSummaryMode = function(m){if(this._opts.summaryMode!==m){this._opts.summaryMode=m;this.render();}};
    P.setOutlineColors = function(colors){Object.assign(this._opts.outlineColors,colors);this.render();};
    P.expandAll = function(){for(var i=0;i<this._flatList.length;i++)this._flatList[i]._expanded=true;this.render();};
    P.collapseAll = function(){for(var i=0;i<this._flatList.length;i++){if(this._flatList[i]._hasChildren)this._flatList[i]._expanded=false;}this.render();};
    P.getTask = function(id){return this._tasks.find(function(t){return t.id===id;})||null;};
    P.updateCustomData = function(d){this._opts.customData=d;this._renderGrid();this._syncH();};

    return{create:function(c,o){return new G(c,o);}};
})();
