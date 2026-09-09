from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source anchor not found")
    return text.replace(old, new, 1)


# ---- GSTextureVK.cpp: image allocations / logical image destruction ----
tex = Path("pcsx2/GS/Renderers/Vulkan/GSTextureVK.cpp")
s = tex.read_text()

s = replace_once(
    s,
    '#include "common/BitUtils.h"\n\n',
    '#include "common/BitUtils.h"\n\n#include <atomic>\n#include <cstdio>\n\n',
    "GSTextureVK includes",
)

anchor = "static VkImageLayout GetVkImageLayout(GSTextureVK::Layout layout)\n"
helper = r'''template <typename... Args>
static void Pi4MemLog(const char* fmt, Args... args)
{
	FILE* fp = std::fopen("/userdata/system/armsx2/armsx2-pi4mem.log", "a");
	if (!fp)
		return;
	std::fprintf(fp, fmt, args...);
	std::fputc('\n', fp);
	std::fflush(fp);
	std::fclose(fp);
}

static std::atomic<u64> s_pi4_img_create_count{0};
static std::atomic<u64> s_pi4_img_create_bytes{0};
static std::atomic<u64> s_pi4_img_destroy_count{0};
static std::atomic<u64> s_pi4_img_destroy_bytes{0};

'''
s = replace_once(s, anchor, helper + anchor, "GSTextureVK helper")

anchor = "\n\tVkImageView view = VK_NULL_HANDLE;\n"
create_log = r'''
	VmaAllocationInfo pi4_ai{};
	vmaGetAllocationInfo(GSDeviceVK::GetInstance()->GetAllocator(), allocation, &pi4_ai);
	const u64 pi4_size = static_cast<u64>(pi4_ai.size);
	const u64 pi4_create_count = s_pi4_img_create_count.fetch_add(1, std::memory_order_relaxed) + 1;
	const u64 pi4_create_bytes = s_pi4_img_create_bytes.fetch_add(pi4_size, std::memory_order_relaxed) + pi4_size;
	if (pi4_create_count <= 8 || (pi4_create_count & 0x3fu) == 0u)
	{
		Pi4MemLog("[PI4MEM] IMG_CREATE count=%llu total_kb=%llu last_kb=%llu usage=%u format=%u size=%dx%d levels=%d",
			static_cast<unsigned long long>(pi4_create_count),
			static_cast<unsigned long long>(pi4_create_bytes / 1024),
			static_cast<unsigned long long>(pi4_size / 1024),
			static_cast<unsigned>(usage), static_cast<unsigned>(format), width, height, levels);
	}
'''
s = replace_once(s, anchor, create_log + anchor, "GSTextureVK create log")

old = '''\tif (m_allocation != VK_NULL_HANDLE)\n\t{\n\t\tif (defer)\n\t\t\tGSDeviceVK::GetInstance()->DeferImageDestruction(m_image, m_allocation);\n\t\telse\n\t\t\tvmaDestroyImage(GSDeviceVK::GetInstance()->GetAllocator(), m_image, m_allocation);\n'''
new = '''\tif (m_allocation != VK_NULL_HANDLE)\n\t{\n\t\tVmaAllocationInfo pi4_ai{};\n\t\tvmaGetAllocationInfo(GSDeviceVK::GetInstance()->GetAllocator(), m_allocation, &pi4_ai);\n\t\tconst u64 pi4_size = static_cast<u64>(pi4_ai.size);\n\t\tconst u64 pi4_destroy_count = s_pi4_img_destroy_count.fetch_add(1, std::memory_order_relaxed) + 1;\n\t\tconst u64 pi4_destroy_bytes = s_pi4_img_destroy_bytes.fetch_add(pi4_size, std::memory_order_relaxed) + pi4_size;\n\t\tif (pi4_destroy_count <= 8 || (pi4_destroy_count & 0x3fu) == 0u)\n\t\t{\n\t\t\tPi4MemLog("[PI4MEM] IMG_DESTROY_LOGICAL count=%llu total_kb=%llu last_kb=%llu",\n\t\t\t\tstatic_cast<unsigned long long>(pi4_destroy_count),\n\t\t\t\tstatic_cast<unsigned long long>(pi4_destroy_bytes / 1024),\n\t\t\t\tstatic_cast<unsigned long long>(pi4_size / 1024));\n\t\t}\n\n\t\tif (defer)\n\t\t\tGSDeviceVK::GetInstance()->DeferImageDestruction(m_image, m_allocation);\n\t\telse\n\t\t\tvmaDestroyImage(GSDeviceVK::GetInstance()->GetAllocator(), m_image, m_allocation);\n'''
s = replace_once(s, old, new, "GSTextureVK destroy log")
tex.write_text(s)


# ---- GSDeviceVK.cpp: deferred buffers/images and cleanup execution ----
dev = Path("pcsx2/GS/Renderers/Vulkan/GSDeviceVK.cpp")
s = dev.read_text()

s = replace_once(
    s,
    "#include <bit>\n",
    "#include <atomic>\n#include <bit>\n#include <cstdio>\n",
    "GSDeviceVK includes",
)

anchor = "\n#ifdef ENABLE_OGL_DEBUG\n"
helper = r'''
template <typename... Args>
static void Pi4MemLog(const char* fmt, Args... args)
{
	FILE* fp = std::fopen("/userdata/system/armsx2/armsx2-pi4mem.log", "a");
	if (!fp)
		return;
	std::fprintf(fp, fmt, args...);
	std::fputc('\n', fp);
	std::fflush(fp);
	std::fclose(fp);
}

static std::atomic<u64> s_pi4_defer_buffer_count{0};
static std::atomic<u64> s_pi4_free_buffer_count{0};
static std::atomic<u64> s_pi4_pending_buffer_count{0};
static std::atomic<u64> s_pi4_pending_buffer_bytes{0};
static std::atomic<u64> s_pi4_defer_image_count{0};
static std::atomic<u64> s_pi4_free_image_count{0};
static std::atomic<u64> s_pi4_pending_image_count{0};
static std::atomic<u64> s_pi4_pending_image_bytes{0};
'''
s = replace_once(s, anchor, "\n" + helper + anchor, "GSDeviceVK helper")

old = """GSDeviceVK::GSDeviceVK()\n{\n#ifdef ENABLE_OGL_DEBUG\n"""
new = """GSDeviceVK::GSDeviceVK()\n{\n\tPi4MemLog("[PI4MEM] TRACE_READY source=GSDeviceVK_ctor");\n#ifdef ENABLE_OGL_DEBUG\n"""
s = replace_once(s, old, new, "GSDeviceVK constructor trace")

old = """void GSDeviceVK::DeferBufferDestruction(VkBuffer object, VmaAllocation allocation)
{
	FrameResources& resources = m_frame_resources[m_current_frame];
	resources.cleanup_resources.push_back(
		[this, object, allocation]() { vmaDestroyBuffer(m_allocator, object, allocation); });
}
"""
new = """void GSDeviceVK::DeferBufferDestruction(VkBuffer object, VmaAllocation allocation)
{
	VmaAllocationInfo ai{};
	vmaGetAllocationInfo(m_allocator, allocation, &ai);
	const u64 bytes = static_cast<u64>(ai.size);
	const u64 scheduled = s_pi4_defer_buffer_count.fetch_add(1, std::memory_order_relaxed) + 1;
	const u64 pending_count = s_pi4_pending_buffer_count.fetch_add(1, std::memory_order_relaxed) + 1;
	const u64 pending_bytes = s_pi4_pending_buffer_bytes.fetch_add(bytes, std::memory_order_relaxed) + bytes;
	if (scheduled <= 8 || (scheduled & 0x3fu) == 0u)
	{
		Pi4MemLog("[PI4MEM] BUF_DEFER scheduled=%llu pending=%llu pending_kb=%llu last_kb=%llu",
			static_cast<unsigned long long>(scheduled), static_cast<unsigned long long>(pending_count),
			static_cast<unsigned long long>(pending_bytes / 1024), static_cast<unsigned long long>(bytes / 1024));
	}

	FrameResources& resources = m_frame_resources[m_current_frame];
	resources.cleanup_resources.push_back([this, object, allocation, bytes]() {
		vmaDestroyBuffer(m_allocator, object, allocation);
		const u64 freed = s_pi4_free_buffer_count.fetch_add(1, std::memory_order_relaxed) + 1;
		const u64 pending_after = s_pi4_pending_buffer_count.fetch_sub(1, std::memory_order_relaxed) - 1;
		const u64 bytes_after = s_pi4_pending_buffer_bytes.fetch_sub(bytes, std::memory_order_relaxed) - bytes;
		if (freed <= 8 || (freed & 0x3fu) == 0u)
		{
			Pi4MemLog("[PI4MEM] BUF_FREE freed=%llu pending=%llu pending_kb=%llu",
				static_cast<unsigned long long>(freed), static_cast<unsigned long long>(pending_after),
				static_cast<unsigned long long>(bytes_after / 1024));
		}
	});
}
"""
s = replace_once(s, old, new, "DeferBufferDestruction")

old = """void GSDeviceVK::DeferImageDestruction(VkImage object, VmaAllocation allocation)
{
	FrameResources& resources = m_frame_resources[m_current_frame];
	resources.cleanup_resources.push_back(
		[this, object, allocation]() { vmaDestroyImage(m_allocator, object, allocation); });
}
"""
new = """void GSDeviceVK::DeferImageDestruction(VkImage object, VmaAllocation allocation)
{
	VmaAllocationInfo ai{};
	vmaGetAllocationInfo(m_allocator, allocation, &ai);
	const u64 bytes = static_cast<u64>(ai.size);
	const u64 scheduled = s_pi4_defer_image_count.fetch_add(1, std::memory_order_relaxed) + 1;
	const u64 pending_count = s_pi4_pending_image_count.fetch_add(1, std::memory_order_relaxed) + 1;
	const u64 pending_bytes = s_pi4_pending_image_bytes.fetch_add(bytes, std::memory_order_relaxed) + bytes;
	if (scheduled <= 8 || (scheduled & 0x3fu) == 0u)
	{
		Pi4MemLog("[PI4MEM] IMG_DEFER scheduled=%llu pending=%llu pending_kb=%llu last_kb=%llu",
			static_cast<unsigned long long>(scheduled), static_cast<unsigned long long>(pending_count),
			static_cast<unsigned long long>(pending_bytes / 1024), static_cast<unsigned long long>(bytes / 1024));
	}

	FrameResources& resources = m_frame_resources[m_current_frame];
	resources.cleanup_resources.push_back([this, object, allocation, bytes]() {
		vmaDestroyImage(m_allocator, object, allocation);
		const u64 freed = s_pi4_free_image_count.fetch_add(1, std::memory_order_relaxed) + 1;
		const u64 pending_after = s_pi4_pending_image_count.fetch_sub(1, std::memory_order_relaxed) - 1;
		const u64 bytes_after = s_pi4_pending_image_bytes.fetch_sub(bytes, std::memory_order_relaxed) - bytes;
		if (freed <= 8 || (freed & 0x3fu) == 0u)
		{
			Pi4MemLog("[PI4MEM] IMG_FREE freed=%llu pending=%llu pending_kb=%llu",
				static_cast<unsigned long long>(freed), static_cast<unsigned long long>(pending_after),
				static_cast<unsigned long long>(bytes_after / 1024));
		}
	});
}
"""
s = replace_once(s, old, new, "DeferImageDestruction")

old = """void GSDeviceVK::CommandBufferCompleted(u32 index)
{
	FrameResources& resources = m_frame_resources[index];

	for (auto& it : resources.cleanup_resources)
"""
new = """void GSDeviceVK::CommandBufferCompleted(u32 index)
{
	FrameResources& resources = m_frame_resources[index];

	if (resources.cleanup_resources.size() >= 32)
	{
		Pi4MemLog("[PI4MEM] CLEANUP frame=%u callbacks=%zu pending_img=%llu pending_img_kb=%llu pending_buf=%llu pending_buf_kb=%llu",
			index, resources.cleanup_resources.size(),
			static_cast<unsigned long long>(s_pi4_pending_image_count.load(std::memory_order_relaxed)),
			static_cast<unsigned long long>(s_pi4_pending_image_bytes.load(std::memory_order_relaxed) / 1024),
			static_cast<unsigned long long>(s_pi4_pending_buffer_count.load(std::memory_order_relaxed)),
			static_cast<unsigned long long>(s_pi4_pending_buffer_bytes.load(std::memory_order_relaxed) / 1024));
	}

	for (auto& it : resources.cleanup_resources)
"""
s = replace_once(s, old, new, "CommandBufferCompleted")

dev.write_text(s)
print("Pi4 Vulkan direct-file allocation tracing injected successfully")
