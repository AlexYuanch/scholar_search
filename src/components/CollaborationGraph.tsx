import { useEffect, useMemo, useRef, useState } from "react"
import { Maximize2, Minimize2 } from "lucide-react"
import { DataSet } from "vis-data"
import { Network } from "vis-network"
import { Button } from "@/components/ui/button"
import type { EdgePaper, ScholarProfile } from "@/types"

type GraphNode = ScholarProfile["graphNodes"][number]
type GraphEdge = ScholarProfile["graphEdges"][number]

interface Props {
  name: string
  coauthors: Array<{ name: string; papers: number }>
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
  font: { size: number; color: string; vadjust?: number }
  borderWidth?: number
}

interface VisEdge {
  id: string
  from: string
  to: string
  width: number
  label: string
  color: { color: string; highlight: string }
  font: { size: number; align: "middle"; color: string; strokeWidth: number }
}

function heatColor(weight: number, maxWeight: number) {
  const ratio = maxWeight <= 1 ? 0 : weight / maxWeight
  if (ratio > 0.8) return "#ef4444"
  if (ratio > 0.6) return "#f97316"
  if (ratio > 0.4) return "#eab308"
  if (ratio > 0.2) return "#22c55e"
  return "#3b82f6"
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
    const container = containerRef.current
    if (!container || !graphNodes.length) return

    networkRef.current?.destroy()

    const nodes = new DataSet(
      graphNodes.map((node): VisNode => {
        const isCenter = node.type === "center"
        const weight = weightByNode.get(node.id) ?? 1
        const color = isCenter ? "#2563eb" : heatColor(weight, maxWeight)
        return {
          id: node.id,
          label: node.name,
          title: isCenter ? `${node.name}\n${t("graph.center_author")}` : `${node.name}\n${weight} ${t("graph.papers_coauthored")}`,
          shape: isCenter ? "star" : "dot",
          size: isCenter ? 32 : 16 + Math.log2(weight + 1) * 4,
          color: {
            background: color,
            border: isCenter ? "#1d4ed8" : color,
            highlight: { background: color, border: "#111827" },
          },
          font: {
            size: isCenter ? 16 : 13,
            color: "#334155",
            vadjust: isCenter ? -4 : 0,
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
        color: { color: "rgba(100, 116, 139, 0.45)", highlight: "#2563eb" },
        font: { size: 11, align: "middle", color: "#64748b", strokeWidth: 3 },
      })),
    )

    const network = new Network(container, { nodes, edges }, {
      autoResize: true,
      interaction: {
        dragNodes: true,
        dragView: true,
        hover: false,
        multiselect: false,
        navigationButtons: true,
        selectConnectedEdges: false,
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
      network.destroy()
      networkRef.current = null
    }
  }, [graphNodes, graphEdges, maxWeight, name, nameById, onEdgeClick, onNodeClick, t, weightByNode])

  if (!graphNodes.length) {
    return <p className="text-sm text-muted-foreground">{t("panel.no_papers")}</p>
  }

  return (
    <div className={fullscreen ? "fixed inset-0 z-50 bg-background p-4" : "relative"}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full bg-primary" />
            <span className="text-muted-foreground">{t("graph.center_author")}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full bg-[#22c55e]" />
            <span className="text-muted-foreground">{t("graph.coauthor")}</span>
          </span>
          <span className="text-muted-foreground">{t("graph.width_hint")}</span>
        </div>
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setFullscreen((value) => !value)}>
          {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </Button>
      </div>

      <div
        ref={containerRef}
        className={fullscreen ? "h-[calc(100vh-5rem)] rounded-md border bg-card" : "h-[520px] rounded-md border bg-card"}
      />

      <p className="mt-2 text-xs text-muted-foreground">{t("graph.operate_hint")}</p>
    </div>
  )
}
