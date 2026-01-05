from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

from .tools.commerce_pdp_scraper_tool import CommercePdpScraperTool
from .tools.commerce_product_data_tool import CommerceProductDataTool
# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class LlmoForCatalog():
    """LlmoForCatalog crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def comparison_agent(self) -> Agent:
        """
        Agent that:
        - Takes a product page URL
        - Uses tools to scrape the webpage and fetch Commerce backend data by SKU
        - Produces a structured comparison of the two sources
        """
        return Agent(
            config=self.agents_config['comparison_agent'],  # type: ignore[index]
            tools=[
                CommercePdpScraperTool(),
                CommerceProductDataTool(),
            ],
            verbose=True,
        )

    @agent
    def optimization_agent(self) -> Agent:
        """
        Agent that:
        - Takes the webpage data and the comparison result
        - Suggests how to optimize human-visible content, hidden metadata,
          and links to LLMO content pages so that GPT agents favor the webpage.
        """
        return Agent(
            config=self.agents_config['optimization_agent'],  # type: ignore[index]
            verbose=True,
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def compare_task(self) -> Task:
        """
        Task for comparison_agent:
        - Use tools to scrape PDP and fetch Commerce data
        - Output a structured diff (matches, mismatches, missing fields, etc.)
        """
        return Task(
            config=self.tasks_config['compare_task'],  # type: ignore[index]
        )

    @task
    def optimize_task(self) -> Task:
        """
        Task for optimization_agent:
        - Consume the compare_task output (and webpage info)
        - Propose optimizations for PDP content + metadata + LLMO links
        """
        return Task(
            config=self.tasks_config['optimize_task'],  # type: ignore[index]
            output_file='llmo_pdp_optimization.md',
            input_results=[
                self.compare_task
            ],        
            # context = [self.compare_task]
        )

    @crew
    def crew(self) -> Crew:
        """Creates the LlmoForCatalog crew."""
        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,    # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
        )