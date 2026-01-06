from typing import List

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent

from .tools.commerce_pdp_scraper_tool import CommercePdpScraperTool
from .tools.commerce_product_data_tool import CommerceProductDataTool


@CrewBase
class LlmoForCatalog:
    """LlmoForCatalog crew (updated pipeline)."""

    agents: List[BaseAgent]
    tasks: List[Task]

    # -------------------------
    # Agents
    # -------------------------

    @agent
    def catalog_comparison_agent(self) -> Agent:
        """
        Agent #1:
        - Takes PDP URL
        - Scrapes webpage via commerce_pdp_scraper
        - Fetches backend data via commerce_product_data_by_sku
        - Produces structured comparison JSON (including raw_sources.webpage/backend)
        """
        return Agent(
            config=self.agents_config["catalog_comparison_agent"],  # type: ignore[index]
            tools=[
                CommercePdpScraperTool(),
                CommerceProductDataTool(),
            ],
            verbose=True,
        )

    @agent
    def product_page_enrichment_agent(self) -> Agent:
        """
        Agent #2:
        - Uses comparison output (including raw_sources.webpage/backend)
        - Produces ONE consolidated PDP webpage-only enrichment proposal:
          (facts surfacing from backend + inferred shopper intent fields)
        - Outputs strict {suggested_changes, explanations}
        """
        return Agent(
            config=self.agents_config["product_page_enrichment_agent"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def product_catalog_enrichment_agent(self) -> Agent:
        """
        Agent #3:
        - Uses comparison output + raw_sources.*
        - Proposes backend catalog enrichments (e.g., catalog.seo.* and optional catalog.pdp.title)
        - Outputs strict {suggested_changes, explanations}
        """
        return Agent(
            config=self.agents_config["product_catalog_enrichment_agent"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def change_synthesizer_agent(self) -> Agent:
        """
        Agent #4:
        - Merges outputs of product_page_enrichment + product_catalog_enrichment
        - Resolves conflicts deterministically
        - Produces one final change plan + validation
        """
        return Agent(
            config=self.agents_config["change_synthesizer_agent"],  # type: ignore[index]
            verbose=True,
        )

    # -------------------------
    # Tasks
    # -------------------------

    @task
    def compare_catalog_vs_webpage_task(self) -> Task:
        """
        Task 1 (Agent #1):
        - Run scraper + backend fetch
        - Output structured comparison JSON
        """
        return Task(
            config=self.tasks_config["compare_catalog_vs_webpage_task"],  # type: ignore[index]
        )

    @task
    def product_page_enrichment_task(self) -> Task:
        """
        Task 2 (Agent #2):
        - Consume comparison output (including raw_sources.webpage/backend)
        - Propose PDP webpage-only enrichment (facts surfacing + shopper intent)
        - Output strict JSON {suggested_changes, explanations}
        """
        return Task(
            config=self.tasks_config["product_page_enrichment_task"],  # type: ignore[index]
            input_results=[self.compare_catalog_vs_webpage_task],
        )

    @task
    def product_catalog_enrichment_task(self) -> Task:
        """
        Task 3 (Agent #3):
        - Consume comparison output (including raw_sources.webpage/backend)
        - Propose backend catalog enrichment (catalog.seo.* and optional catalog.pdp.title)
        - Output strict JSON {suggested_changes, explanations}
        """
        return Task(
            config=self.tasks_config["product_catalog_enrichment_task"],  # type: ignore[index]
            input_results=[self.compare_catalog_vs_webpage_task],
        )

    @task
    def synthesize_final_change_plan_task(self) -> Task:
        """
        Task 4 (Agent #4):
        - Merge Agents #2 and #3 results
        - Resolve conflicts deterministically
        - Output final change plan JSON + validation
        """
        return Task(
            config=self.tasks_config["synthesize_final_change_plan_task"],  # type: ignore[index]
            input_results=[
                self.compare_catalog_vs_webpage_task,
                self.product_page_enrichment_task,
                self.product_catalog_enrichment_task,
            ],
            output_file="suggestions_and_explanations.json",
        )

    # -------------------------
    # Crew
    # -------------------------

    @crew
    def crew(self) -> Crew:
        """Creates the LlmoForCatalog crew."""
        return Crew(
            agents=self.agents,  # auto-created by @agent decorators
            tasks=self.tasks,    # auto-created by @task decorators
            process=Process.sequential,
            verbose=True,
        )
