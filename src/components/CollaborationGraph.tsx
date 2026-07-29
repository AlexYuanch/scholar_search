import { useEffect, useMemo, useRef, useState } from "react"
import { LocateFixed, Maximize2, Minimize2 } from "lucide-react"
import { DataSet } from "vis-data"
import { Network } from "vis-network"
import { Button } from "@/components/ui/button"
import type { EdgePaper, ScholarProfile } from "@/types"

type GraphNode = ScholarProfile["graphNodes"][number]
type GraphEdge = ScholarProfile["graphEdges"][number]

interface Props {
  name: string
  graphNodes: GraphNode[]
  graphEdges: GraphEdge[]
  topics?: string[]
  onEdgeClick?: (data: { sourceName: string; targetName: string; papers: EdgePaper[]; weight: number }) => void
  onNodeClick?: (data: { id: string; name: string; type: string; papers: EdgePaper[]; weight: number }) => void
  onFullscreenChange?: (fs: boolean) => void
  t: (key: string) => string
}

interface GraphClickParams {
  nodes: string[]
  edges: string[]
  event?: {
    preventDefault?: () => void
  }
}

interface VisNode {
  id: string
  label: string
  title: string
  shape: "star" | "dot"
  size: number
  color: {
    background: string
    border: string
    highlight: { background: string; border: string }
  }
  font: {
    size: number
    color: string
    vadjust?: number
    strokeWidth?: number
    strokeColor?: string
  }
  borderWidth?: number
}

interface VisEdge {
  id: string
  from: string
  to: string
  width: number
  label: string
  color: { color: string; highlight: string }
  font: {
    size: number
    align: "middle"
    color: string
    strokeWidth: number
    strokeColor: string
  }
}

interface GraphPalette {
  center: string
  centerBorder: string
  low: string
  medium: string
  high: string
  peak: string
  edge: string
  label: string
  labelStroke: string
}

function themeColor(styles: CSSStyleDeclaration, name: string, fallback: string) {
  return styles.getPropertyValue(name).trim() || fallback
}

function heatColor(weight: number, maxWeight: number, palette: GraphPalette) {
  const ratio = maxWeight <= 1 ? 0 : weight / maxWeight
  if (ratio > 0.78) return palette.peak
  if (ratio > 0.5) return palette.high
  if (ratio > 0.25) return palette.medium
  return palette.low
}

export default function CollaborationGraph({
  name,
  graphNodes,
  graphEdges,
  onEdgeClick,
  onNodeClick,
  onFullscreenChange,
  t,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const networkRef = useRef<Network | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [themeRevision, setThemeRevision] = useState(0)

  const nameById = useMemo(
    () => new Map(graphNodes.map((node) => [node.id, node.name])),
    [graphNodes],
  )

  const weightByNode = useMemo(() => {
    const map = new Map<string, number>()
    for (const edge of graphEdges) {
      map.set(edge.target, Math.max(map.get(edge.target) ?? 0, edge.weight))
    }
    return map
  }, [graphEdges])

  const maxWeight = useMemo(
    () => Math.max(1, ...graphEdges.map((edge) => edge.weight)),
    [graphEdges],
  )

  useEffect(() => {
    onFullscreenChange?.(fullscreen)
  }, [fullscreen, onFullscreenChange])

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeRevision((value) => value + 1))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !graphNodes.length) return

    networkRef.current?.destroy()
    const styles = window.getComputedStyle(document.documentElement)
    const palette: GraphPalette = {
      center: themeColor(styles, "--graph-center", "#287f73"),
      centerBorder: themeColor(styles, "--graph-center-border", "#185f57"),
      low: themeColor(styles, "--graph-low", "#8aaca0"),
      medium: themeColor(styles, "--graph-medium", "#66869a"),
      high: themeColor(styles, "--graph-high", "#b38a4c"),
      peak: themeColor(styles, "--graph-peak", "#b56f62"),
      edge: themeColor(styles, "--graph-edge", "rgba(86, 113, 105, 0.36)"),
      label: themeColor(styles, "--graph-label", "#34443d"),
      labelStroke: themeColor(styles, "--graph-label-stroke", "#faf9f5"),
    }

    const nodes = new DataSet(
      graphNodes.map((node): VisNode => {
        const isCenter = node.type === "center"
        const weight = weightByNode.get(node.id) ?? 1
        const color = isCenter ? palette.center : heatColor(weight, maxWeight, palette)
        const shortId = node.id.split("/").filter(Boolean).at(-1) ?? node.id
        const publicationAffiliation = node.institution?.trim()
        const identity = publicationAffiliation || shortId
        return {
          id: node.id,
          label: node.name,
          title: isCenter
            ? `${node.name}\n${t("graph.center_author")}`
            : `${node.name}\n${
                publicationAffiliation
                  ? `${t("graph.publication_affiliation")}: ${publicationAffiliation}`
                  : identity
              }\n${weight} ${t("graph.papers_coauthored")}`,
          shape: isCenter ? "star" : "dot",
          size: isCenter ? 32 : 16 + Math.log2(weight + 1) * 4,
          color: {
            background: color,
            border: isCenter ? palette.centerBorder : color,
            highlight: { background: color, border: palette.label },
          },
          font: {
            size: isCenter ? 16 : 13,
            color: palette.label,
            vadjust: isCenter ? -4 : 0,
            strokeWidth: 3,
            strokeColor: palette.labelStroke,
          },
          borderWidth: isCenter ? 3 : 1,
        }
      }),
    )

    const edges = new DataSet(
      graphEdges.map((edge, index): VisEdge => ({
        id: `${edge.source}-${edge.target}-${index}`,
        from: edge.source,
        to: edge.target,
        width: 1 + Math.sqrt(edge.weight),
        label: edge.weight > 1 ? `${edge.weight}${t("graph.edge_label")}` : "",
        color: { color: palette.edge, highlight: palette.center },
        font: {
          size: 11,
          align: "middle",
          color: palette.label,
          strokeWidth: 3,
          strokeColor: palette.labelStroke,
        },
      })),
    )

    const network = new Network(container, { nodes, edges }, {
      autoResize: true,
      interaction: {
        dragNodes: true,
        dragView: true,
        hover: true,
        hoverConnectedEdges: true,
        multiselect: false,
        navigationButtons: true,
        selectConnectedEdges: false,
        tooltipDelay: 180,
        zoomSpeed: 0.15,
      },
      physics: {
        stabilization: { enabled: true, iterations: 200 },
        barnesHut: {
          gravitationalConstant: -2600,
          centralGravity: 0.25,
          springLength: 130,
          springConstant: 0.04,
        },
      },
      nodes: {
        shadow: { enabled: true, color: "rgba(15, 23, 42, 0.16)", size: 8, x: 1, y: 2 },
      },
      edges: {
        smooth: { enabled: true, type: "dynamic", roundness: 0.5 },
        selectionWidth: 2,
      },
    })

    networkRef.current = network
    let resizeTimer: number | undefined
    const resizeObserver = new ResizeObserver(() => {
      window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(() => {
        network.redraw()
        network.fit({ animation: false })
      }, 120)
    })
    resizeObserver.observe(container)

    network.on("hoverNode", () => {
      container.style.cursor = "pointer"
    })
    network.on("hoverEdge", () => {
      container.style.cursor = "pointer"
    })
    network.on("blurNode", () => {
      container.style.cursor = ""
    })
    network.on("blurEdge", () => {
      container.style.cursor = ""
    })

    network.on("click", (params: GraphClickParams) => {
      const clickedEdge = params.edges[0]
      const clickedNode = params.nodes[0]

      if (clickedEdge) {
        const edge = edges.get(clickedEdge)
        const raw = graphEdges.find((item) => item.source === edge?.from && item.target === edge?.to)
        if (raw) {
          onEdgeClick?.({
            sourceName: nameById.get(raw.source) ?? name,
            targetName: nameById.get(raw.target) ?? raw.target,
            papers: raw.papers ?? [],
            weight: raw.weight,
          })
        }
        return
      }

      if (clickedNode) {
        const node = graphNodes.find((item) => item.id === clickedNode)
        if (!node) return
        const raw = graphEdges.find((item) => item.target === clickedNode)
        onNodeClick?.({
          id: node.id,
          name: node.name,
          type: node.type,
          papers: raw?.papers ?? [],
          weight: raw?.weight ?? graphEdges.length,
        })
      }
    })

    network.on("oncontext", (params: GraphClickParams) => {
      params.event?.preventDefault?.()
      const nodeId = params.nodes[0]
      const node = graphNodes.find((item) => item.id === nodeId)
      if (node?.type === "coauthor" && node.id.startsWith("http")) {
        window.open(node.id, "_blank", "noopener,noreferrer")
      }
    })

    return () => {
      window.clearTimeout(resizeTimer)
      resizeObserver.disconnect()
      network.destroy()
      networkRef.current = null
    }
  }, [graphNodes, graphEdges, maxWeight, name, nameById, onEdgeClick, onNodeClick, t, themeRevision, weightByNode])

  if (!graphNodes.length) {
    return <p className="text-sm text-muted-foreground">{t("panel.no_papers")}</p>
  }

  return (
    <div className={fullscreen ? "fixed inset-0 z-50 bg-background p-4" : "relative"}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full bg-[var(--graph-center)]" />
            <span className="text-muted-foreground">{t("graph.center_author")}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full bg-[var(--graph-low)]" />
            <span className="text-muted-foreground">{t("graph.strength_low")}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full bg-[var(--graph-medium)]" />
            <span className="text-muted-foreground">{t("graph.strength_medium")}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full bg-[var(--graph-high)]" />
            <span className="text-muted-foreground">{t("graph.strength_high")}</span>
          </span>
          <span className="text-muted-foreground">{t("graph.width_hint")}</span>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8"
            title={t("graph.reset_view")}
            aria-label={t("graph.reset_view")}
            onClick={() => networkRef.current?.fit({
              animation: { duration: 350, easingFunction: "easeInOutQuad" },
            })}
          >
            <LocateFixed className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8"
            title={fullscreen ? t("graph.exit_fullscreen") : t("graph.fullscreen")}
            aria-label={fullscreen ? t("graph.exit_fullscreen") : t("graph.fullscreen")}
            onClick={() => setFullscreen((value) => !value)}
          >
            {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      <div
        ref={containerRef}
        className={`scholar-collaboration-canvas ${
          fullscreen
            ? "h-[calc(100dvh-5rem)] rounded-md border"
            : "h-[clamp(22rem,58dvh,32.5rem)] rounded-md border"
        }`}
      />

      <p className="mt-2 text-xs text-muted-foreground">{t("graph.operate_hint")}</p>
    </div>
  )
}
