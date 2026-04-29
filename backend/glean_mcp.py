"""
Glean MCP Client for S2 Report Sniffer
Integrates with Glean MCP server to fetch contextual insights for reports.

Architecture:
- Retrieval planner: Finding-type-based query templates
- Evidence ranking: Weighted scoring for support usefulness
- Synthesis engine: Structured incident brief output
"""

import logging
import json
import httpx
import subprocess
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


# Canonical finding types from architecture
FINDING_TYPES = [
    "replication_lag",
    "replication_stopped",
    "memory_pressure",
    "swap_usage",
    "disk_latency",
    "partition_skew",
    "topology_mismatch",
    "version_inconsistency",
    "orphan_databases",
    "config_anomaly"
]

SEVERITY_LEVELS = ["critical", "high", "medium", "low", "info"]

DEPLOYMENT_TYPES = ["self-managed", "cloud", "unknown"]


@dataclass
class Evidence:
    """Evidence supporting a finding."""
    collector: str
    node: Optional[str] = None
    metric: Optional[str] = None
    value: Optional[str] = None
    raw_snippet: Optional[str] = None


@dataclass
class Finding:
    """Canonical finding structure."""
    id: str
    type: str
    severity: str
    title: str
    summary: str
    evidence: List[Evidence]
    keywords: List[str]
    affected_nodes: List[str]
    version: str
    time_range: Optional[Dict[str, str]] = None


@dataclass
class IncidentBrief:
    """Structured incident brief."""
    report_id: str
    analyzed_at: str
    top_severity: str
    findings: List[Finding]
    total_findings: int
    critical_count: int
    high_count: int
    summary: str


@dataclass
class GleanSearchResult:
    """Normalized Glean search result."""
    id: str
    title: str
    url: str
    snippet: str
    source: str
    updated_at: str
    author: Optional[str] = None
    score: float = 0.0
    symptom_match: float = 0.0
    version_match: float = 0.0
    recency: float = 0.0
    source_authority: float = 0.0


@dataclass
class FindingEnrichment:
    """Glean enrichment for a single finding."""
    finding_id: str
    queries: List[str]
    docs: List[GleanSearchResult]
    cases: List[GleanSearchResult]
    people: List[Dict[str, str]]
    fetched_at: str
    has_results: bool


@dataclass
class EnrichmentResult:
    """Complete enrichment result for a report."""
    report_id: str
    finding_enrichments: List[FindingEnrichment]
    enriched_at: str
    retrieval_plan: List[Dict[str, Any]]
    recommendations: List[str]


class GleanMCPClient:
    """
    Client for Glean MCP (Model Context Protocol) server communication.
    
    Supports both local stdio-based MCP servers and remote HTTP-based MCP servers.
    """
    
    def __init__(
        self,
        base_url: str,
        api_token: str = "",
        port: int = 3000,
        use_remote: bool = False,
        timeout: int = 30
    ):
        """
        Initialize GleanMCPClient.
        
        Args:
            base_url: Glean instance URL or base URL for MCP server
            api_token: API token for authentication (for remote MCP)
            port: Local MCP server port (for local MCP)
            use_remote: Whether to use remote MCP server (HTTP) or local MCP server (stdio)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.port = port
        self.use_remote = use_remote
        self.timeout = timeout
        
        if use_remote:
            # Remote MCP server - connect via HTTP to Glean instance
            self.mcp_url = f"{self.base_url}/mcp/default"
        else:
            # Local MCP server - connect via stdio
            self.mcp_url = None
            self._process = None
            self._initialized = False
    
    async def _start_stdio_server(self) -> bool:
        """Start the local MCP server via npx if not already running."""
        if self._process is not None and self._process.poll() is None:
            return True
        
        try:
            # Set up environment with GLEAN_INSTANCE
            env = os.environ.copy()
            if self.base_url:
                env["GLEAN_INSTANCE"] = self.base_url
            
            # Start the MCP server using npx
            self._process = subprocess.Popen(
                ["npx", "@gleanwork/mcp-server@latest"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            
            # Initialize the MCP connection
            await self._initialize_stdio()
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False
    
    async def _initialize_stdio(self) -> None:
        """Initialize the stdio MCP connection."""
        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "s2-report-sniffer",
                    "version": "1.0.0"
                }
            }
        }
        
        try:
            if self._process and self._process.stdin:
                self._process.stdin.write(json.dumps(init_request) + "\n")
                self._process.stdin.flush()
                
                # Read response
                response_line = self._process.stdout.readline()
                if response_line:
                    response = json.loads(response_line)
                    logger.debug(f"Initialize response: {response}")
        except Exception as e:
            logger.error(f"Failed to initialize stdio connection: {e}")
    
    async def _send_stdio_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request via stdio and return the response."""
        if not self._initialized:
            await self._start_stdio_server()
        
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": method,
            "params": params or {}
        }
        
        try:
            if self._process and self._process.stdin:
                self._process.stdin.write(json.dumps(request) + "\n")
                self._process.stdin.flush()
                
                # Read response
                response_line = self._process.stdout.readline()
                if response_line:
                    response = json.loads(response_line)
                    return response
        except Exception as e:
            logger.error(f"Failed to send stdio request: {e}")
            return {"error": str(e)}
        
        return {"error": "No response from MCP server"}
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check if Glean MCP server is reachable.
        
        Returns:
            dict with status "ok" or error details
        """
        if not self.use_remote:
            # Local MCP server - check via stdio
            try:
                # Try to start/communicate with stdio MCP server
                if not self._initialized:
                    success = await self._start_stdio_server()
                    if not success:
                        return {
                            "status": "error",
                            "message": "Failed to start local MCP server. Please ensure npx @gleanwork/mcp-server@latest is available."
                        }
                
                # Send a ping request (or tools/list to check if server is responding)
                response = await self._send_stdio_request("tools/list")
                if "error" in response:
                    return {
                        "status": "error",
                        "message": f"Local MCP server communication failed: {response['error']}"
                    }
                
                return {
                    "status": "ok",
                    "message": "Local MCP server is running and communicating via stdio"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Local MCP server check failed: {str(e)}"
                }
        else:
            # Remote MCP server - check via HTTP
            try:
                headers = {}
                if self.api_token:
                    headers["Authorization"] = f"Bearer {self.api_token}"
                
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(f"{self.mcp_url}/health", headers=headers)
                    
                    if response.status_code == 200:
                        return {"status": "ok", "message": "Remote MCP server reachable"}
                    elif response.status_code == 401:
                        return {"status": "auth_required", "message": "OAuth authentication required. Please complete OAuth flow."}
                    else:
                        return {"status": "error", "message": f"Remote MCP server returned {response.status_code}"}
            except httpx.ConnectError:
                return {
                    "status": "error",
                    "message": f"Remote MCP server not reachable at {self.mcp_url}. Check URL and network."
                }
            except Exception as e:
                return {"status": "error", "message": f"Remote MCP server check failed: {str(e)}"}
    
    async def fetch_related_insights(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None,
        datasource: str = "cases"
    ) -> List[Dict[str, Any]]:
        """
        Fetch related insights from Glean based on query and context.
        
        Args:
            query: Search query string
            context: Additional context (report metadata, errors, etc.)
            datasource: Glean datasource to search (cases, articles, etc.)
        
        Returns:
            List of insight dicts with keys: title, url, snippet, source
        """
        if self.use_remote:
            # Remote MCP server - use HTTP
            if not self.mcp_url:
                logger.warning("Glean MCP not configured, skipping insights fetch")
                return []
            
            try:
                # Build MCP JSON-RPC request
                mcp_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "glean_search",
                        "arguments": {
                            "query": query,
                            "datasource": datasource,
                            "context": context or {}
                        }
                    }
                }
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.mcp_url,
                        json=mcp_request,
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if "result" in result and "content" in result["result"]:
                            # Parse MCP tool response
                            content = result["result"]["content"]
                            if isinstance(content, list) and len(content) > 0:
                                insights_text = content[0].get("text", "")
                                if insights_text:
                                    try:
                                        insights = json.loads(insights_text)
                                        if isinstance(insights, list):
                                            return self._normalize_insights(insights)
                                    except json.JSONDecodeError:
                                        logger.warning(f"Failed to parse insights JSON: {insights_text}")
                    
                    logger.warning(f"Glean search returned no results: {response.status_code}")
                    return []
                    
            except httpx.TimeoutException:
                logger.warning("Glean search timeout")
                return []
            except httpx.ConnectError:
                logger.warning("Glean MCP server unreachable during search")
                return []
            except Exception as e:
                logger.warning(f"Glean search failed: {e}")
                return []
        else:
            # Local MCP server - use stdio
            try:
                # First, list available tools to find the correct search tool name
                tools_response = await self._send_stdio_request("tools/list")
                
                if "error" in tools_response:
                    logger.warning(f"Failed to list tools: {tools_response['error']}")
                    return []
                
                # Find the search tool
                search_tool_name = None
                if "result" in tools_response and "tools" in tools_response["result"]:
                    for tool in tools_response["result"]["tools"]:
                        if "search" in tool.get("name", "").lower():
                            search_tool_name = tool["name"]
                            break
                
                if not search_tool_name:
                    logger.warning("No search tool found in Glean MCP server")
                    return []
                
                logger.debug(f"Using search tool: {search_tool_name}")
                
                # Use the Glean MCP server's search tool via stdio
                response = await self._send_stdio_request(
                    "tools/call",
                    {
                        "name": search_tool_name,
                        "arguments": {
                            "query": query
                        }
                    }
                )
                
                if "error" in response:
                    logger.warning(f"Stdio MCP request failed: {response['error']}")
                    return []
                
                if "result" in response and "content" in response["result"]:
                    content = response["result"]["content"]
                    if isinstance(content, list) and len(content) > 0:
                        insights_text = content[0].get("text", "")
                        if insights_text:
                            try:
                                insights = json.loads(insights_text)
                                if isinstance(insights, list):
                                    return self._normalize_insights(insights)
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse insights JSON: {insights_text}")
                
                return []
                
            except Exception as e:
                logger.warning(f"Stdio Glean search failed: {e}")
                return []
    
    def _normalize_insights(self, raw_insights: List[Dict]) -> List[Dict[str, Any]]:
        """
        Normalize raw Glean insights to standard format.
        
        Args:
            raw_insights: Raw insights from Glean
        
        Returns:
            Normalized insights with keys: title, url, snippet, source
        """
        normalized = []
        for item in raw_insights:
            insight = {
                "title": item.get("title", "Untitled"),
                "url": item.get("url", "#"),
                "snippet": item.get("snippet", item.get("description", ""))[:200],
                "source": item.get("source", "Glean"),
                "relevance": item.get("relevance", 0.0),
                "updated_at": item.get("updated_at", datetime.now().isoformat()),
                "author": item.get("author")
            }
            normalized.append(insight)
        
        # Sort by relevance
        normalized.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return normalized[:10]  # Return top 10
    
    # Retrieval playbooks - finding-type-based query templates
    RETRIEVAL_PLAYBOOKS = {
        "replication_lag": {
            "doc_queries": [
                "SingleStore replication lag runbook {version}",
                "showReplicationStatus high lag fix",
                "replication behind leaf node"
            ],
            "case_queries": [
                "replication lag incident {version}",
                "replica seconds_behind support case resolution"
            ],
            "people_queries": [
                "SingleStore replication subsystem engineer"
            ],
            "datasources": ["KB", "support_tickets", "engineering_docs"],
            "days_back": 90
        },
        "replication_stopped": {
            "doc_queries": [
                "SingleStore replication stopped recovery {version}",
                "HA replication failure runbook"
            ],
            "case_queries": [
                "replication stopped incident recovery"
            ],
            "people_queries": [
                "SingleStore HA replication owner"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 180
        },
        "memory_pressure": {
            "doc_queries": [
                "SingleStore memoryCommitted high runbook {version}",
                "memory pressure OLAP workload mitigation"
            ],
            "case_queries": [
                "memory pressure OOM incident {version}",
                "memoryCommitted 90 percent support"
            ],
            "people_queries": [
                "SingleStore memory management engineer"
            ],
            "datasources": ["KB", "support_tickets"],
            "days_back": 90
        },
        "swap_usage": {
            "doc_queries": [
                "SingleStore swap usage impact performance",
                "disable swap Linux SingleStore recommendation"
            ],
            "case_queries": [
                "swap usage leaf node degradation incident"
            ],
            "people_queries": [
                "SingleStore performance engineer"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 180
        },
        "disk_latency": {
            "doc_queries": [
                "SingleStore disk latency high runbook",
                "diskLatency write p99 degradation {version}"
            ],
            "case_queries": [
                "disk latency incident leaf node {version}"
            ],
            "people_queries": [
                "SingleStore storage performance engineer"
            ],
            "datasources": ["KB", "support_tickets"],
            "days_back": 90
        },
        "partition_skew": {
            "doc_queries": [
                "SingleStore partition skew rebalance runbook {version}",
                "explainRebalancePartitions skew fix"
            ],
            "case_queries": [
                "partition skew incident resolution"
            ],
            "people_queries": [
                "SingleStore partitioning engineer"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 90
        },
        "topology_mismatch": {
            "doc_queries": [
                "SingleStore topology mismatch repair {version}",
                "clusterTopology inconsistency fix"
            ],
            "case_queries": [
                "topology mismatch incident {version}"
            ],
            "people_queries": [
                "SingleStore cluster topology engineer"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 180
        },
        "version_inconsistency": {
            "doc_queries": [
                "SingleStore version mismatch nodes upgrade {version}",
                "mixed version cluster support"
            ],
            "case_queries": [
                "version inconsistency incident {version}"
            ],
            "people_queries": [
                "SingleStore upgrade engineer"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 180
        },
        "orphan_databases": {
            "doc_queries": [
                "SingleStore orphan databases cleanup procedure",
                "orphanDatabases runbook"
            ],
            "case_queries": [
                "orphan database incident resolution"
            ],
            "people_queries": [
                "SingleStore database lifecycle engineer"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 180
        },
        "config_anomaly": {
            "doc_queries": [
                "SingleStore configuration anomaly {version}",
                "showVariables best practices"
            ],
            "case_queries": [
                "config anomaly support case"
            ],
            "people_queries": [
                "SingleStore configuration engineer"
            ],
            "datasources": ["KB", "engineering_docs"],
            "days_back": 90
        }
    }
    
    def build_query_from_report(self, report_data: Dict[str, Any]) -> str:
        """
        Build a Glean search query from parsed report data.
        
        Args:
            report_data: Parsed report data with cluster_overview, recommendations, etc.
        
        Returns:
            Search query string for Glean
        """
        parts = []
        
        # Extract cluster info
        overview = report_data.get("cluster_overview", {})
        if overview.get("cluster_name"):
            parts.append(overview["cluster_name"])
        
        # Extract error types from recommendations
        recs = report_data.get("recommendations", [])
        error_types = set()
        for rec in recs[:5]:  # Top 5 recommendations
            if rec.get("check_id"):
                error_types.add(rec["check_id"])
            if rec.get("title"):
                parts.append(rec["title"])
        
        # Extract node info
        nodes = report_data.get("nodes", [])
        if nodes:
            node_hosts = [n.get("hostname", "") for n in nodes[:3] if n.get("hostname")]
            if node_hosts:
                parts.append(" ".join(node_hosts))
        
        # Extract version
        version = report_data.get("version")
        if version:
            parts.append(f"SingleStore {version}")
        
        # Build query
        query = " ".join(parts) if parts else "SingleStore cluster issues"
        
        # Limit query length
        if len(query) > 500:
            query = query[:500]
        
        return query
    
    def build_retrieval_plan(self, findings: List[Finding], report_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Build retrieval plan from findings using playbooks.
        
        Args:
            findings: List of Finding objects
            report_metadata: Report metadata (version, deployment_type, etc.)
        
        Returns:
            List of retrieval plans with queries and filters
        """
        plans = []
        version = report_metadata.get("version", "")
        deployment_type = report_metadata.get("deployment_type", "unknown")
        
        # Only process top 5 findings by severity to avoid overwhelming Glean
        sorted_findings = sorted(findings, key=lambda f: self._severity_weight(f.severity), reverse=True)
        
        for finding in sorted_findings[:5]:
            playbook = self.RETRIEVAL_PLAYBOOKS.get(finding.type)
            if not playbook:
                continue
            
            # Interpolate version into queries
            doc_queries = [q.format(version=version) if "{version}" in q else q 
                           for q in playbook["doc_queries"]]
            case_queries = [q.format(version=version) if "{version}" in q else q 
                            for q in playbook["case_queries"]]
            people_queries = playbook["people_queries"]
            
            plan = {
                "finding_id": finding.id,
                "finding_type": finding.type,
                "finding_severity": finding.severity,
                "doc_queries": doc_queries,
                "case_queries": case_queries,
                "people_queries": people_queries,
                "datasources": playbook["datasources"],
                "days_back": playbook["days_back"],
                "keywords": finding.keywords,
                "version": version,
                "deployment_type": deployment_type
            }
            plans.append(plan)
        
        return plans
    
    def _severity_weight(self, severity: str) -> int:
        """Return numeric weight for severity sorting."""
        weights = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
        return weights.get(severity, 0)
    
    def rank_evidence(self, results: List[GleanSearchResult], finding: Finding, 
                     report_metadata: Dict[str, Any]) -> List[GleanSearchResult]:
        """
        Rank evidence by support usefulness using weighted scoring.
        
        Scoring formula:
        score = 0.30 * symptom_match + 0.20 * version_match + 0.15 * recency + 
                0.15 * source_authority + 0.10 * case_resolution + 0.10 * cross_source
        
        Args:
            results: Raw Glean search results
            finding: The finding being enriched
            report_metadata: Report metadata
        
        Returns:
            Ranked results with scores
        """
        version = report_metadata.get("version", "")
        finding_keywords = set(finding.keywords)
        
        for result in results:
            # Symptom match (30%)
            symptom_match = self._calculate_symptom_match(result, finding_keywords)
            
            # Version match (20%)
            version_match = self._calculate_version_match(result, version)
            
            # Recency (15%)
            recency = self._calculate_recency(result)
            
            # Source authority (15%)
            source_authority = self._calculate_source_authority(result)
            
            # Case resolution strength (10%)
            case_resolution = self._calculate_case_resolution(result)
            
            # Cross-source agreement (10%)
            cross_source = 0.1  # Simplified - would need multiple sources
            
            # Calculate final score
            result.score = (
                0.30 * symptom_match +
                0.20 * version_match +
                0.15 * recency +
                0.15 * source_authority +
                0.10 * case_resolution +
                0.10 * cross_source
            )
            
            # Store component scores for audit
            result.symptom_match = symptom_match
            result.version_match = version_match
            result.recency = recency
            result.source_authority = source_authority
        
        # Sort by score
        ranked = sorted(results, key=lambda r: r.score, reverse=True)
        return ranked[:10]  # Return top 10
    
    def _calculate_symptom_match(self, result: GleanSearchResult, keywords: set) -> float:
        """Calculate symptom match score (0-1)."""
        text = f"{result.title} {result.snippet}".lower()
        matches = sum(1 for kw in keywords if kw.lower() in text)
        return min(matches / max(len(keywords), 1), 1.0)
    
    def _calculate_version_match(self, result: GleanSearchResult, version: str) -> float:
        """Calculate version match score (0-1)."""
        if not version:
            return 0.5
        text = f"{result.title} {result.snippet}".lower()
        version_lower = version.lower()
        if version_lower in text:
            return 1.0
        return 0.3
    
    def _calculate_recency(self, result: GleanSearchResult) -> float:
        """Calculate recency score (0-1)."""
        try:
            updated_at = datetime.fromisoformat(result.updated_at.replace("Z", "+00:00"))
            days_old = (datetime.now(updated_at.tzinfo) - updated_at).days
            if days_old < 30:
                return 1.0
            elif days_old < 90:
                return 0.7
            elif days_old < 180:
                return 0.4
            else:
                return 0.1
        except Exception:
            return 0.5
    
    def _calculate_source_authority(self, result: GleanSearchResult) -> float:
        """Calculate source authority score (0-1)."""
        source = result.source.lower()
        if source in ["kb", "engineering_docs", "advisories"]:
            return 1.0
        elif source in ["support_tickets", "postmortems"]:
            return 0.8
        elif source in ["slack", "confluence"]:
            return 0.6
        else:
            return 0.4
    
    def _calculate_case_resolution(self, result: GleanSearchResult) -> float:
        """Calculate case resolution strength (0-1)."""
        # Simplified - would need actual resolution data
        source = result.source.lower()
        if source in ["support_tickets", "postmortems"]:
            return 0.8
        return 0.5
    
    async def enrich_findings(
        self, 
        findings: List[Finding], 
        report_metadata: Dict[str, Any]
    ) -> EnrichmentResult:
        """
        Enrich findings with Glean evidence.
        
        Args:
            findings: List of Finding objects
            report_metadata: Report metadata
        
        Returns:
            EnrichmentResult with docs, cases, people for each finding
        """
        report_id = report_metadata.get("report_id", "unknown")
        retrieval_plan = self.build_retrieval_plan(findings, report_metadata)
        
        finding_enrichments = []
        
        for plan in retrieval_plan:
            finding_id = plan["finding_id"]
            
            # Run queries in parallel
            docs_results, cases_results, people_results = await self._run_parallel_queries(plan)
            
            # Rank evidence
            finding = next((f for f in findings if f.id == finding_id), None)
            if finding:
                docs_ranked = self.rank_evidence(docs_results, finding, report_metadata)
                cases_ranked = self.rank_evidence(cases_results, finding, report_metadata)
            else:
                docs_ranked = docs_results
                cases_ranked = cases_results
            
            enrichment = FindingEnrichment(
                finding_id=finding_id,
                queries=plan["doc_queries"] + plan["case_queries"],
                docs=[asdict(r) for r in docs_ranked],
                cases=[asdict(r) for r in cases_ranked],
                people=people_results,
                fetched_at=datetime.now().isoformat(),
                has_results=len(docs_ranked) > 0 or len(cases_ranked) > 0
            )
            finding_enrichments.append(enrichment)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(findings, finding_enrichments)
        
        return EnrichmentResult(
            report_id=report_id,
            finding_enrichments=[asdict(fe) for fe in finding_enrichments],
            enriched_at=datetime.now().isoformat(),
            retrieval_plan=retrieval_plan,
            recommendations=recommendations
        )
    
    async def _run_parallel_queries(self, plan: Dict[str, Any]) -> Tuple[List, List, List]:
        """Run doc, case, and people queries in parallel."""
        import asyncio
        
        tasks = []
        for query in plan["doc_queries"]:
            tasks.append(self.fetch_related_insights(query, datasource="docs"))
        for query in plan["case_queries"]:
            tasks.append(self.fetch_related_insights(query, datasource="cases"))
        
        # People queries handled separately (different API)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        docs_results = []
        cases_results = []
        people_results = []
        
        # Process results
        doc_count = len(plan["doc_queries"])
        case_count = len(plan["case_queries"])
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Query failed: {result}")
                continue
            if i < doc_count:
                docs_results.extend(result)
            else:
                cases_results.extend(result)
        
        # Normalize to GleanSearchResult
        docs_normalized = [self._to_glean_result(r) for r in docs_results]
        cases_normalized = [self._to_glean_result(r) for r in cases_results]
        
        return docs_normalized, cases_normalized, people_results
    
    def _to_glean_result(self, raw: Dict) -> GleanSearchResult:
        """Convert raw result to GleanSearchResult."""
        return GleanSearchResult(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            url=raw.get("url", "#"),
            snippet=raw.get("snippet", "")[:200],
            source=raw.get("source", "Glean"),
            updated_at=raw.get("updated_at", datetime.now().isoformat()),
            author=raw.get("author"),
            score=raw.get("relevance", 0.0)
        )
    
    def _generate_recommendations(
        self, 
        findings: List[Finding], 
        enrichments: List[FindingEnrichment]
    ) -> List[str]:
        """Generate recommendations based on findings and enrichments."""
        recommendations = []
        
        # Check for critical findings
        critical_findings = [f for f in findings if f.severity == "critical"]
        if critical_findings:
            recommendations.append("Immediate attention required for critical findings")
        
        # Check for enrichment coverage
        enriched_findings = [e for e in enrichments if e.has_results]
        if len(enriched_findings) < len(findings):
            recommendations.append("Some findings lack Glean enrichment - consider manual review")
        
        # Version-specific recommendations
        versions = set(f.version for f in findings if f.version)
        if len(versions) > 1:
            recommendations.append("Version inconsistency detected - review cluster upgrade status")
        
        return recommendations


class GleanConfigManager:
    """Manages Glean configuration persistence."""
    
    CONFIG_DIR = Path.home() / ".config" / "s2-report-sniffer"
    CONFIG_FILE = CONFIG_DIR / "glean_config.json"
    
    @classmethod
    def _ensure_config_dir(cls):
        """Ensure config directory exists."""
        cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """
        Load Glean configuration from file.
        
        Returns:
            Config dict with keys: glean_url, oauth_enabled, client_id, client_secret, 
                                   access_token, refresh_token, token_expires_at, mcp_port, enabled
        """
        cls._ensure_config_dir()
        
        if not cls.CONFIG_FILE.exists():
            return cls._default_config()
        
        try:
            with open(cls.CONFIG_FILE, "r") as f:
                config = json.load(f)
                # Merge with defaults to handle missing keys
                default = cls._default_config()
                default.update(config)
                return default
        except Exception as e:
            logger.warning(f"Failed to load Glean config: {e}")
            return cls._default_config()
    
    @classmethod
    def save_config(cls, config: Dict[str, Any]) -> bool:
        """
        Save Glean configuration to file.
        
        Args:
            config: Config dict with OAuth or API token settings
        
        Returns:
            True if save succeeded, False otherwise
        """
        cls._ensure_config_dir()
        
        try:
            with open(cls.CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
            logger.info(f"Glean config saved to {cls.CONFIG_FILE}")
            return True
        except Exception as e:
            logger.error(f"Failed to save Glean config: {e}")
            return False
    
    @classmethod
    def _default_config(cls) -> Dict[str, Any]:
        """Return default Glean configuration."""
        return {
            "glean_url": "",
            "mcp_port": 3000,
            "enabled": False
        }
    
    @classmethod
    def get_client(cls) -> Optional[GleanMCPClient]:
        """
        Get configured GleanMCPClient instance.
        
        Returns:
            GleanMCPClient instance or None if not configured
        """
        config = cls.load_config()
        
        if not config.get("enabled"):
            return None
        
        glean_url = config.get("glean_url", "").strip()
        mcp_port = config.get("mcp_port", 3000)
        
        if not glean_url:
            logger.warning("Glean enabled but URL missing")
            return None
        
        return GleanMCPClient(
            base_url=glean_url,
            api_token="",  # Not needed for MCP server connection
            port=mcp_port,
            use_remote=False
        )
