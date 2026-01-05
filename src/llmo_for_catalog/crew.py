from typing import List

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent

from .tools.commerce_pdp_scraper_tool import CommercePdpScraperTool
from .tools.commerce_product_data_tool import CommerceProductDataTool


@CrewBase
class LlmoForCatalog:
    """LlmoForCatalog crew (5-agent pipeline)."""

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
        - Produces structured comparison JSON
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
    def product_facts_enrichment_agent(self) -> Agent:
        """
        Agent #2:
        - Uses comparison output
        - Suggests factual enrichments from backend that are missing/weak on webpage
        - Outputs strict {suggested_changes, explanations}
        """
        return Agent(
            config=self.agents_config["product_facts_enrichment_agent"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def shopper_intent_enrichment_agent(self) -> Agent:
        """
        Agent #3:
        - Uses comparison output
        - Suggests intent fields (use_context, target_personas)
        - Outputs strict {suggested_changes, explanations}
        """
        return Agent(
            config=self.agents_config["shopper_intent_enrichment_agent"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def seo_visible_content_optimization_agent(self) -> Agent:
        """
        Agent #4:
        - Uses comparison output + scraped seo fields
        - Optimizes title tag, meta description, H1 (and optionally PDP title)
        - Outputs strict {suggested_changes, explanations}
        """
        return Agent(
            config=self.agents_config["seo_visible_content_optimization_agent"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def change_synthesizer_agent(self) -> Agent:
        """
        Agent #5:
        - Merges outputs of Agents 2/3/4
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
    def product_facts_enrichment_task(self) -> Task:
        """
        Task 2 (Agent #2):
        - Consume comparison output
        - Propose factual enrichments
        - Output strict JSON {suggested_changes, explanations}
        """
        return Task(
            config=self.tasks_config["product_facts_enrichment_task"],  # type: ignore[index]
            context=[self.compare_catalog_vs_webpage_task],
        )

    @task
    def shopper_intent_enrichment_task(self) -> Task:
        """
        Task 3 (Agent #3):
        - Consume comparison output
        - Propose intent enrichment fields
        - Output strict JSON {suggested_changes, explanations}
        """
        return Task(
            config=self.tasks_config["shopper_intent_enrichment_task"],  # type: ignore[index]
            context=[self.compare_catalog_vs_webpage_task],
        )

    @task
    def seo_visible_content_optimization_task(self) -> Task:
        """
        Task 4 (Agent #4):
        - Consume comparison output
        - Propose SEO tag improvements
        - Output strict JSON {suggested_changes, explanations}
        """
        return Task(
            config=self.tasks_config["seo_visible_content_optimization_task"],  # type: ignore[index]
            context=[self.compare_catalog_vs_webpage_task],
        )

    @task
    def synthesize_final_change_plan_task(self) -> Task:
        """
        Task 5 (Agent #5):
        - Merge Agents 2/3/4 results
        - Resolve conflicts
        - Output final change plan JSON + validation
        """
        return Task(
            config=self.tasks_config["synthesize_final_change_plan_task"],  # type: ignore[index]
            context=[
                self.compare_catalog_vs_webpage_task,
                self.product_facts_enrichment_task,
                self.shopper_intent_enrichment_task,
                self.seo_visible_content_optimization_task,
            ],
            output_file="catalog_change_plan.json",
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