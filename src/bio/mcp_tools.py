"""
MCP tools for scheduler configuration and management
"""
import json
import os
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp import types

from .schedulers.factory import (
    get_scheduler, detect_available_schedulers, 
    validate_scheduler_config, get_scheduler_config_status
)
from .schedulers.base import ResourceRequest
from .schedulers.slurm_scheduler import SlurmSettings

server = Server("bio-mcp-queue-config")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available MCP tools for scheduler configuration"""
    return [
        types.Tool(
            name="check_scheduler_status",
            description="Check the status of available job schedulers and their configuration",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="configure_scheduler",
            description="Interactive configuration wizard for job schedulers",
            inputSchema={
                "type": "object",
                "properties": {
                    "scheduler_type": {
                        "type": "string",
                        "enum": ["auto", "slurm", "celery"],
                        "description": "Preferred scheduler type"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="set_slurm_config",
            description="Configure Slurm scheduler settings",
            inputSchema={
                "type": "object",
                "properties": {
                    "partition": {
                        "type": "string",
                        "description": "Default Slurm partition"
                    },
                    "account": {
                        "type": "string",
                        "description": "Slurm account to charge jobs to"
                    },
                    "qos": {
                        "type": "string",
                        "description": "Quality of Service (QoS)"
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory for job files"
                    },
                    "modules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Modules to load in job scripts"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="test_scheduler",
            description="Test scheduler configuration by submitting a simple test job",
            inputSchema={
                "type": "object",
                "properties": {
                    "scheduler_type": {
                        "type": "string",
                        "enum": ["auto", "slurm", "celery"],
                        "description": "Scheduler to test"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_scheduler_recommendations",
            description="Get recommendations for scheduler setup based on current environment",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="save_scheduler_config",
            description="Save scheduler configuration to environment file",
            inputSchema={
                "type": "object",
                "properties": {
                    "config_file": {
                        "type": "string",
                        "description": "Path to save configuration (.env file)"
                    },
                    "scheduler_type": {
                        "type": "string",
                        "enum": ["auto", "slurm", "celery"]
                    },
                    "slurm_settings": {
                        "type": "object",
                        "properties": {
                            "partition": {"type": "string"},
                            "account": {"type": "string"},
                            "qos": {"type": "string"},
                            "work_dir": {"type": "string"}
                        }
                    }
                },
                "required": ["config_file"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle MCP tool calls"""
    
    if name == "check_scheduler_status":
        return await check_scheduler_status()
    
    elif name == "configure_scheduler":
        return await configure_scheduler(
            scheduler_type=arguments.get("scheduler_type", "auto")
        )
    
    elif name == "set_slurm_config":
        return await set_slurm_config(arguments)
    
    elif name == "test_scheduler":
        return await test_scheduler(
            scheduler_type=arguments.get("scheduler_type", "auto")
        )
    
    elif name == "get_scheduler_recommendations":
        return await get_scheduler_recommendations()
    
    elif name == "save_scheduler_config":
        return await save_scheduler_config(arguments)
    
    else:
        raise ValueError(f"Unknown tool: {name}")


async def check_scheduler_status() -> list[types.TextContent]:
    """Check scheduler status and configuration"""
    try:
        available = await detect_available_schedulers()
        config_status = get_scheduler_config_status()
        validation = await validate_scheduler_config()
        
        status_report = {
            "available_schedulers": available,
            "configuration": config_status,
            "validation": validation
        }
        
        # Create user-friendly summary
        summary = []
        summary.append("## Scheduler Status Report\n")
        
        summary.append("### Available Schedulers:")
        for scheduler, is_available in available.items():
            status = "✅ Available" if is_available else "❌ Not Available"
            summary.append(f"- **{scheduler.title()}**: {status}")
        
        summary.append("\n### Configuration:")
        summary.append(f"- Requested scheduler: {config_status['requested_scheduler']}")
        summary.append(f"- Fallback enabled: {config_status['fallback_enabled']}")
        summary.append(f"- Slurm configured: {'✅' if config_status['slurm_configured'] else '❌'}")
        summary.append(f"- Celery configured: {'✅' if config_status['celery_configured'] else '❌'}")
        
        if validation["recommendations"]:
            summary.append("\n### Recommendations:")
            for rec in validation["recommendations"]:
                summary.append(f"- {rec}")
        
        if validation["missing_config"]:
            summary.append("\n### Missing Configuration:")
            for missing in validation["missing_config"]:
                summary.append(f"- {missing}")
        
        return [
            types.TextContent(
                type="text",
                text="\n".join(summary) + f"\n\n**Raw Data:**\n```json\n{json.dumps(status_report, indent=2)}\n```"
            )
        ]
        
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error checking scheduler status: {str(e)}"
            )
        ]


async def configure_scheduler(scheduler_type: str = "auto") -> list[types.TextContent]:
    """Interactive scheduler configuration"""
    try:
        validation = await validate_scheduler_config(scheduler_type)
        
        if validation["valid"]:
            return [
                types.TextContent(
                    type="text",
                    text=f"✅ Scheduler configuration is valid!\n\n"
                         f"Available schedulers: {validation['available_schedulers']}\n"
                         f"You can start submitting jobs immediately."
                )
            ]
        
        # Provide configuration guidance
        guidance = []
        guidance.append(f"## Scheduler Configuration for '{scheduler_type}'\n")
        
        if scheduler_type == "auto" or scheduler_type == "slurm":
            if not validation["available_schedulers"].get("slurm", False):
                guidance.append("### Setting up Slurm:")
                guidance.append("1. Ensure Slurm is installed and `sbatch` is in your PATH")
                guidance.append("2. Check your Slurm configuration:")
                guidance.append("   ```bash")
                guidance.append("   sinfo  # Show available partitions")
                guidance.append("   sacctmgr show account  # Show available accounts")
                guidance.append("   ```")
                guidance.append("3. Set environment variables:")
                guidance.append("   - `BIO_SLURM_PARTITION` (optional)")
                guidance.append("   - `BIO_SLURM_ACCOUNT` (optional)")
                guidance.append("   - `BIO_SLURM_QOS` (optional)")
        
        if scheduler_type == "auto" or scheduler_type == "celery":
            if not validation["available_schedulers"].get("celery", False):
                guidance.append("\n### Setting up Celery:")
                guidance.append("1. Start Redis server:")
                guidance.append("   ```bash")
                guidance.append("   redis-server")
                guidance.append("   ```")
                guidance.append("2. Set Redis URL:")
                guidance.append("   ```bash")
                guidance.append("   export BIO_QUEUE_REDIS_URL=redis://localhost:6379/0")
                guidance.append("   ```")
                guidance.append("3. Start Celery workers:")
                guidance.append("   ```bash")
                guidance.append("   cd bio-mcp-queue")
                guidance.append("   celery -A src.celery_app worker --loglevel=info")
                guidance.append("   ```")
        
        if validation["recommendations"]:
            guidance.append("\n### Additional Recommendations:")
            for rec in validation["recommendations"]:
                guidance.append(f"- {rec}")
        
        guidance.append("\n### Next Steps:")
        guidance.append("1. Complete the setup steps above")
        guidance.append("2. Run `check_scheduler_status` to verify configuration")
        guidance.append("3. Use `test_scheduler` to run a test job")
        
        return [
            types.TextContent(
                type="text",
                text="\n".join(guidance)
            )
        ]
        
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error configuring scheduler: {str(e)}"
            )
        ]


async def set_slurm_config(config: Dict[str, Any]) -> list[types.TextContent]:
    """Set Slurm configuration"""
    try:
        env_vars = []
        
        if config.get("partition"):
            os.environ["BIO_SLURM_PARTITION"] = config["partition"]
            env_vars.append(f"BIO_SLURM_PARTITION={config['partition']}")
        
        if config.get("account"):
            os.environ["BIO_SLURM_ACCOUNT"] = config["account"]
            env_vars.append(f"BIO_SLURM_ACCOUNT={config['account']}")
        
        if config.get("qos"):
            os.environ["BIO_SLURM_QOS"] = config["qos"]
            env_vars.append(f"BIO_SLURM_QOS={config['qos']}")
        
        if config.get("work_dir"):
            os.environ["BIO_SLURM_WORK_DIR"] = config["work_dir"]
            env_vars.append(f"BIO_SLURM_WORK_DIR={config['work_dir']}")
        
        if config.get("modules"):
            modules_str = ":".join(config["modules"])
            os.environ["BIO_SLURM_MODULES"] = modules_str
            env_vars.append(f"BIO_SLURM_MODULES={modules_str}")
        
        return [
            types.TextContent(
                type="text",
                text=f"✅ Slurm configuration updated!\n\n"
                     f"Environment variables set:\n" + 
                     "\n".join(f"- {var}" for var in env_vars) +
                     f"\n\n💡 To make these permanent, add them to your shell profile or use `save_scheduler_config`."
            )
        ]
        
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error setting Slurm configuration: {str(e)}"
            )
        ]


async def test_scheduler(scheduler_type: str = "auto") -> list[types.TextContent]:
    """Test scheduler by submitting a test job"""
    try:
        scheduler = await get_scheduler(scheduler_type)
        
        # Create a simple test job
        test_job_id = f"test-{scheduler.scheduler_type}-{int(asyncio.get_event_loop().time())}"
        
        test_params = {
            "command": "echo 'Hello from bio-mcp-queue test job'",
            "test": True
        }
        
        result = await scheduler.submit_job(
            job_id=test_job_id,
            job_type="test",
            parameters=test_params,
            resources=ResourceRequest(cpus=1, memory_mb=100, walltime_minutes=5)
        )
        
        # Wait a moment and check status
        await asyncio.sleep(2)
        status = await scheduler.get_job_status(test_job_id)
        
        return [
            types.TextContent(
                type="text",
                text=f"✅ Test job submitted successfully!\n\n"
                     f"- Scheduler: {scheduler.scheduler_type}\n"
                     f"- Job ID: {test_job_id}\n"
                     f"- Scheduler Job ID: {result}\n"
                     f"- Current Status: {status}\n\n"
                     f"The scheduler is working correctly!"
            )
        ]
        
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"❌ Test job failed: {str(e)}\n\n"
                     f"This indicates a configuration issue. Run `configure_scheduler` for guidance."
            )
        ]


async def get_scheduler_recommendations() -> list[types.TextContent]:
    """Get scheduler recommendations based on environment"""
    try:
        available = await detect_available_schedulers()
        
        recommendations = []
        recommendations.append("## Scheduler Recommendations\n")
        
        if available.get("slurm", False) and available.get("celery", False):
            recommendations.append("🎉 **Both schedulers are available!**")
            recommendations.append("\n**Recommendations:**")
            recommendations.append("- Use `auto` mode to automatically prefer Slurm with Celery fallback")
            recommendations.append("- Slurm is better for:")
            recommendations.append("  - Large computational clusters")
            recommendations.append("  - Jobs requiring specific resource allocations")
            recommendations.append("  - Integration with HPC environments")
            recommendations.append("- Celery is better for:")  
            recommendations.append("  - Development and testing")
            recommendations.append("  - Smaller workloads")
            recommendations.append("  - Container-based deployments")
        
        elif available.get("slurm", False):
            recommendations.append("✅ **Slurm is available**")
            recommendations.append("- Perfect for HPC environments")
            recommendations.append("- Configure partition and account for optimal resource allocation")
            recommendations.append("- Consider setting up Celery as a fallback for development")
        
        elif available.get("celery", False):
            recommendations.append("✅ **Celery is available**")
            recommendations.append("- Great for development and moderate workloads")
            recommendations.append("- Ensure Redis is properly configured and persistent")
            recommendations.append("- Monitor worker capacity for large job volumes")
        
        else:
            recommendations.append("❌ **No schedulers available**")
            recommendations.append("\n**Setup Options:**")
            recommendations.append("1. **Quick Start (Celery):**")
            recommendations.append("   - Start Redis: `redis-server`")
            recommendations.append("   - Start workers: `celery -A src.celery_app worker`")
            recommendations.append("2. **HPC Setup (Slurm):**")
            recommendations.append("   - Ensure Slurm is installed and configured")
            recommendations.append("   - Set partition/account environment variables")
        
        # Add environment-specific recommendations
        recommendations.append("\n### Environment-Specific Tips:")
        
        # Check if running in container
        if Path("/.dockerenv").exists():
            recommendations.append("- 🐳 **Docker detected**: Celery is recommended for containerized deployments")
        
        # Check if common HPC modules are available
        try:
            result = await asyncio.create_subprocess_exec(
                "module", "avail",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await result.communicate()
            if result.returncode == 0:
                recommendations.append("- 🏢 **HPC environment detected**: Slurm with modules is recommended")
        except:
            pass
        
        return [
            types.TextContent(
                type="text",
                text="\n".join(recommendations)
            )
        ]
        
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error generating recommendations: {str(e)}"
            )
        ]


async def save_scheduler_config(config: Dict[str, Any]) -> list[types.TextContent]:
    """Save scheduler configuration to file"""
    try:
        config_file = Path(config["config_file"])
        
        # Create configuration content
        config_lines = ["# Bio-MCP Queue Scheduler Configuration", ""]
        
        if config.get("scheduler_type"):
            config_lines.append(f"BIO_MCP_SCHEDULER_TYPE={config['scheduler_type']}")
        
        if config.get("slurm_settings"):
            config_lines.append("\n# Slurm Configuration")
            slurm = config["slurm_settings"]
            
            if slurm.get("partition"):
                config_lines.append(f"BIO_SLURM_PARTITION={slurm['partition']}")
            if slurm.get("account"):
                config_lines.append(f"BIO_SLURM_ACCOUNT={slurm['account']}")
            if slurm.get("qos"):
                config_lines.append(f"BIO_SLURM_QOS={slurm['qos']}")
            if slurm.get("work_dir"):
                config_lines.append(f"BIO_SLURM_WORK_DIR={slurm['work_dir']}")
        
        # Write to file
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, 'w') as f:
            f.write('\n'.join(config_lines))
        
        return [
            types.TextContent(
                type="text",
                text=f"✅ Configuration saved to {config_file}\n\n"
                     f"To use this configuration:\n"
                     f"```bash\n"
                     f"source {config_file}\n"
                     f"```\n\n"
                     f"Or add to your shell profile for permanent use."
            )
        ]
        
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error saving configuration: {str(e)}"
            )
        ]


if __name__ == "__main__":
    import mcp.server.stdio
    mcp.server.stdio.run_server(server)