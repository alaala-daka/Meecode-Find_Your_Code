/** 概念图画布:SVG + d3-force 宿主 + 缩放平移 + 气泡/节点卡浮层。 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, zoomTransform, type ZoomBehavior } from "d3-zoom";
import { useGraphStore } from "../store/graphStore";
import { useSessionStore } from "../store/sessionStore";
import { useUiStore } from "../store/uiStore";
import { useReaderStore, readerWidth } from "../store/readerStore";
import { useIsMobile } from "../../utils/useIsMobile";
import {
  animateZoomTo,
  clampWorldToViewport,
  ensureVisibleTransform,
  fitTransform,
  graphBBox,
} from "../graph/zoomFit";
import { GraphSimulation } from "../graph/simulation";
import { handleNodeClick, handleNodeDoubleClick, isVisibleInPractice } from "../graph/controller";
import { EdgeMarkerDefs, EdgeView } from "./EdgeView";
import { NodeView } from "./NodeView";
import { EdgeBubble } from "./EdgeBubble";
import { NodeCard } from "./NodeCard";

interface Transform {
  x: number;
  y: number;
  k: number;
}

export function GraphCanvas() {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<GraphSimulation | null>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [tf, setTf] = useState<Transform>({ x: 0, y: 0, k: 1 });
  const prevNodeIdsRef = useRef<Set<string> | null>(null);
  const ensureTimerRef = useRef<number | undefined>(undefined);
  const ensureCancelRef = useRef<(() => void) | null>(null);
  const dragSettleCancelRef = useRef<(() => void) | null>(null);

  // 订阅两个计数器:tick(每帧位置)/ structureVersion(结构)
  const tick = useGraphStore((s) => s.tick);
  const structureVersion = useGraphStore((s) => s.structureVersion);
  const nodes = useGraphStore((s) => s.nodes);
  const edges = useGraphStore((s) => s.edges);
  const rootId = useGraphStore((s) => s.rootId);

  const mode = useSessionStore((s) => s.mode);
  const practiceExpanded = useSessionStore((s) => s.practiceExpanded);
  const practiceRevealed = useSessionStore((s) => s.practiceRevealed);

  const selectedEdgeId = useUiStore((s) => s.selectedEdgeId);
  const selectEdge = useUiStore((s) => s.selectEdge);
  const cardNodeId = useUiStore((s) => s.cardNodeId);
  const setCardNode = useUiStore((s) => s.setCardNode);

  // 模拟生命周期
  useEffect(() => {
    simRef.current = new GraphSimulation(() => useGraphStore.getState().bumpTick());
    return () => simRef.current?.stop();
  }, []);

  // 缩放平移(初始居中)
  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const initial = { x: rect.width / 2, y: rect.height / 2, k: 1 };
    const z = zoom<SVGSVGElement, unknown>()
      // 显式 extent = 容器尺寸(与默认行为等价):避免 d3 默认读取 svg viewBox/width.baseVal,
      // 该属性 jsdom 未实现,组件测试渲染画布会崩
      .extent(() => {
        const r = containerRef.current?.getBoundingClientRect();
        return [[0, 0], [r?.width || 800, r?.height || 600]] as [[number, number], [number, number]];
      })
      .scaleExtent([0.4, 2.5])
      .filter((event) => {
        if (event.type === "wheel") return true;
        const target = event.target as Element;
        return target === svgRef.current || target.classList?.contains("zoom-bg");
      })
      .on("zoom", (event) => {
        setTf({ x: event.transform.x, y: event.transform.y, k: event.transform.k });
      });
    zoomRef.current = z;
    select(svgRef.current).call(z).call(z.transform, zoomIdentity.translate(initial.x, initial.y));
  }, []);

  /** 可视区实测:画布容器尺寸;阅读器打开时扣除其占宽(阅读器不算空白区)。
   * 容器不可测(jest/jsdom)时退回窗口尺寸。 */
  const measureView = useCallback((readerOpen: boolean) => {
    const rect = containerRef.current?.getBoundingClientRect();
    const rw = readerOpen ? readerWidth() : 0;
    const width = rect && rect.width > 0 ? rect.width : window.innerWidth;
    const height = rect && rect.height > 0 ? rect.height : window.innerHeight;
    return { width: Math.max(120, width - rw), height: Math.max(120, height) };
  }, []);

  /** 把整图 bbox 收进当前空白区:阅读器开→全幅 fit;关→尽量只平移居中,装不下才缩放。
   * 返回动画取消函数。 */
  const fitToView = useCallback(
    (duration = 340): (() => void) | null => {
      const svg = svgRef.current;
      const z = zoomRef.current;
      if (!svg || !z) return null;
      const open = useReaderStore.getState().open;
      const view = measureView(open);
      const bbox = graphBBox(Object.values(useGraphStore.getState().nodes));
      if (!bbox) return null;
      const current = zoomTransform(svg);
      const target = open
        ? fitTransform(bbox, view.width, view.height, 80)
        : ensureVisibleTransform(bbox, view.width, view.height, current, 80);
      return animateZoomTo(svg, z, target, duration);
    },
    [measureView],
  );

  // 阅读器开合/开着时结构变化 → 图内容 zoom-fit 进剩余可视区(节点不被遮挡)
  const readerOpen = useReaderStore((s) => s.open);
  const isMobile = useIsMobile();
  // 移动端整屏阅读态:图已隐藏(opacity:0),跳过一切重排;退出阅读态由下方 fit 全幅归位
  const graphHidden = isMobile && readerOpen;
  useEffect(() => {
    const svg = svgRef.current;
    const z = zoomRef.current;
    if (!svg || !z) return;
    if (graphHidden) return;
    let cancel: (() => void) | null = null;
    let timer: number | undefined;

    const fit = () => {
      cancel?.(); // 取消上一段未完成的动画
      cancel = fitToView();
    };

    if (readerOpen) {
      fit();
      // 开着期间结构变化(新展开)也重排,防抖 400ms 等力场稍稳
      let last = useGraphStore.getState().structureVersion;
      const unsub = useGraphStore.subscribe((s) => {
        if (s.structureVersion === last) return;
        last = s.structureVersion;
        window.clearTimeout(timer);
        timer = window.setTimeout(fit, 400);
      });
      return () => {
        unsub();
        window.clearTimeout(timer);
        cancel?.();
      };
    }
    fit(); // 关闭 → 全幅重排
    return () => cancel?.();
  }, [readerOpen, graphHidden, fitToView]);

  // 阅读器关闭时,新生成节点后整图自动居中进空白区(视口内→仅平移保留缩放,越界→缩放收回)
  useEffect(() => {
    const currentIds = new Set(Object.keys(useGraphStore.getState().nodes));
    const prev = prevNodeIdsRef.current;
    const hasNewNodes = prev ? [...currentIds].some((id) => !prev.has(id)) : false;
    prevNodeIdsRef.current = currentIds;
    if (!hasNewNodes || readerOpen) return;

    window.clearTimeout(ensureTimerRef.current);
    ensureTimerRef.current = window.setTimeout(() => {
      ensureCancelRef.current?.(); // 取消上一段未完成的回收动画
      ensureCancelRef.current = fitToView(340);
    }, 180);

    return () => {
      window.clearTimeout(ensureTimerRef.current);
    };
  }, [structureVersion, readerOpen, fitToView]);

  // 容器尺寸变化(窗口缩放/布局抖动)→ 整图重新收进空白区
  useEffect(() => {
    if (graphHidden) return;
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let timer: number | undefined;
    let lastW = el.getBoundingClientRect().width;
    let lastH = el.getBoundingClientRect().height;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      if (Math.abs(r.width - lastW) < 1 && Math.abs(r.height - lastH) < 1) return;
      lastW = r.width;
      lastH = r.height;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        ensureCancelRef.current?.();
        ensureCancelRef.current = fitToView(340);
      }, 200);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
    };
  }, [readerOpen, graphHidden, fitToView]);

  // 卸载时停掉可能在飞的动画
  useEffect(
    () => () => {
      ensureCancelRef.current?.();
      dragSettleCancelRef.current?.();
    },
    [],
  );

  // 拖拽边界约束:拖拽中的世界坐标被夹取,节点屏幕圆不出空白区
  const constrainNodePosition = useCallback(
    (x: number, y: number, r: number) => {
      const svg = svgRef.current;
      if (!svg) return { x, y };
      const t = zoomTransform(svg);
      const view = measureView(useReaderStore.getState().open);
      return clampWorldToViewport(x, y, r, t, view.width, view.height, 20);
    },
    [measureView],
  );

  // 拖拽松手:碰撞可能把相邻节点挤出边界 → 整图检查,越界则平移收回(保留用户缩放)
  const handleDragSettle = useCallback(() => {
    const svg = svgRef.current;
    const z = zoomRef.current;
    if (!svg || !z) return;
    const bbox = graphBBox(Object.values(useGraphStore.getState().nodes));
    if (!bbox) return;
    const current = zoomTransform(svg);
    const view = measureView(useReaderStore.getState().open);
    const target = ensureVisibleTransform(bbox, view.width, view.height, current, 8);
    if (
      target === current ||
      (Math.abs(target.x - current.x) < 0.5 &&
        Math.abs(target.y - current.y) < 0.5 &&
        Math.abs(target.k - current.k) < 0.001)
    ) {
      return;
    }
    dragSettleCancelRef.current?.();
    dragSettleCancelRef.current = animateZoomTo(svg, z, target, 320);
  }, [measureView]);

  // 可见集合(练习模式按重现进度裁剪)
  const visibleNodes = useMemo(() => {
    const all = Object.values(nodes);
    if (mode !== "practice") return all;
    return all.filter((n) => isVisibleInPractice(n.id, rootId, practiceExpanded, nodes));
  }, [nodes, mode, rootId, practiceExpanded, tick]);

  const visibleEdges = useMemo(() => {
    const visible = new Set(visibleNodes.map((n) => n.id));
    return Object.values(edges).filter((e) => visible.has(e.from) && visible.has(e.to));
  }, [edges, visibleNodes]);

  // 结构同步进物理模拟
  useEffect(() => {
    simRef.current?.setGraph(visibleNodes, visibleEdges);
  }, [structureVersion, mode, practiceExpanded]);

  const sim = simRef.current;
  const toScreen = (gx: number, gy: number) => ({ x: tf.x + gx * tf.k, y: tf.y + gy * tf.k });

  const selectedEdge = selectedEdgeId ? edges[selectedEdgeId] : null;
  const cardNode = cardNodeId ? nodes[cardNodeId] : null;

  // 浮层夹取边界:画布容器尺寸(容错 jsdom 取 0 时退回窗口)
  const bounds = useMemo(() => {
    const rect = containerRef.current?.getBoundingClientRect();
    return {
      width: rect && rect.width > 0 ? rect.width : window.innerWidth,
      height: rect && rect.height > 0 ? rect.height : window.innerHeight,
    };
    // tick 变化时重算,保持浮层 clamp 跟随最新容器尺寸
  }, [tick]);

  return (
    <div ref={containerRef} className="graph-canvas">
      <svg ref={svgRef} width="100%" height="100%">
        <EdgeMarkerDefs />
        <g transform={`translate(${tf.x},${tf.y}) scale(${tf.k})`}>
          {/* 平移热区背景 */}
          <rect
            className="zoom-bg"
            x={-6000}
            y={-6000}
            width={12000}
            height={12000}
            fill="transparent"
            onClick={() => selectEdge(null)}
          />
          {visibleEdges.map((e) => (
            <EdgeView
              key={e.id}
              edge={e}
              nodes={nodes}
              selected={e.id === selectedEdgeId}
              onClick={(id) => {
                selectEdge(id);
                setCardNode(null);
              }}
            />
          ))}
          {sim &&
            visibleNodes.map((n) => (
              <NodeView
                key={n.id}
                node={n}
                sim={sim}
                masked={mode === "practice" && !practiceRevealed.includes(n.id)}
                onClick={handleNodeClick}
                onDoubleClick={handleNodeDoubleClick}
                constrain={constrainNodePosition}
                onDragEnd={handleDragSettle}
              />
            ))}
        </g>
      </svg>

      {/* 关系气泡(F6) */}
      {selectedEdge && nodes[selectedEdge.from] && nodes[selectedEdge.to] && (
        <EdgeBubble
          edge={selectedEdge}
          anchor={toScreen(
            (nodes[selectedEdge.from].x + nodes[selectedEdge.to].x) / 2,
            (nodes[selectedEdge.from].y + nodes[selectedEdge.to].y) / 2,
          )}
          parentTitle={nodes[selectedEdge.from].title}
          childTitle={nodes[selectedEdge.to].title}
          masked={mode === "practice" && !practiceRevealed.includes(selectedEdge.to)}
          bounds={bounds}
        />
      )}

      {/* 焦点节点内容卡 */}
      {cardNode && (
        <NodeCard
          node={cardNode}
          anchor={toScreen(cardNode.x, cardNode.y)}
          masked={mode === "practice" && !practiceRevealed.includes(cardNode.id)}
          bounds={bounds}
        />
      )}
    </div>
  );
}
