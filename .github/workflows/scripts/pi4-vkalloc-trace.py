from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source anchor not found")
    return text.replace(old, new, 1)


# Instrument Vulkan image allocations and logical image destruction.
tex = Path("pcsx2/GS/Renderers/Vulkan/GSTextureVK.cpp")
s = tex.read_text()

s = replace_once(
    s,
    '#include "common/BitUtils.h"\n\n',
    '#include "common/BitUtils.h"\n\n#include <atomic>\n\n',
    "GSTextureVK include",
)

anchor = "static VkImageLayout GetVkImageLayout(GSTextureVK::Layout layout)\n"
counters = """static std::atomic<u64> s_pi4_img_create_count{0};
static std::atomic<u64> s_pi4_img_create_bytes{0};
static std::atomic<u64> s_pi4_img_destroy_count{0};
static std::atomic<u64> s_pi4_img_destroy_bytes{0};

"""
s = replace_once(s, anchor, counters + anchor, "GSTextureVK counters")

anchor = "\n\tVkImageView view = VK_NULL_HANDLE;\n"
create_log = r'''
	VmaAllocationInfo pi4_ai{};
	vmaGetAllocationInfo(GSDeviceVK::GetInstance()->GetAllocator(), allocation, &pi4_ai);
	const u64 pi4_size = static_cast<u64>(pi4_ai.size);
	const u64 pi4_create_count = s_pi4_img_create_count.fetch_add(1, std::memory_order_relaxed) + 1;
	const u64 pi4_create_bytes = s_pi4_img_create_bytes.fetch_add(pi4_size, std::memory_order_relaxed) + pi4_size;
	if ((pi4_create_count & 0xffu) == 0u)
	{
		Console.WriteLn("[PI4MEM] IMG_CREATE count=%llu total_kb=%llu last_kb=%llu usage=%u format=%u size=%dx%d levels=%d",
			static_cast<unsigned long long>(pi4_create_count),
			static_cast<unsigned long long>(pi4_create_bytes / 1024),
			static_cast<unsigned long long>(pi4_size / 1024),
			static_cast<unsigned>(usage), static_cast<unsigned>(format), width, height, levels);
	}
'''
s = replace_once(s, anchor, create_log + anchor, "GSTextureVK create log")

old = r'''	if (m_allocation != VK_NULL_HANDLE)
	{
		if (defer)
			GSDeviceVK::GetInstance()->DeferImageDestruction(m_image, m_allocation);
		else
			vmaDestroyImage(GSDeviceVK::GetInstance()->GetAllocator(), m_image, m_allocation);
'''.replace("\\t", "\t").replace("\\n", "\n")
new = r'''	if (m_allocation != VK_NULL_HANDLE)
	{
		VmaAllocationInfo pi4_ai{};
		vmaGetAllocationInfo(GSDeviceVK::GetInstance()->GetAllocator(), m_allocation, &pi4_ai);
		const u64 pi4_size = static_cast<u64>(pi4_ai.size);
		const u64 pi4_destroy_count = s_pi4_img_destroy_count.fetch_add(1, std::memory_order_relaxed) + 1;
		const u64 pi4_destroy_bytes = s_pi4_img_destroy_bytes.fetch_add(pi4_size, std::memory_order_relaxed) + pi4_size;
		if ((pi4_destroy_count & 0xffu) == 0u)
		{
			Console.WriteLn("[PI4MEM] IMG_DESTROY_LOGICAL count=%llu total_kb=%llu last_kb=%llu",
				static_cast<unsigned long long>(pi4_destroy_count),
				static_cast<unsigned long long>(pi4_destroy_bytes / 1024),
				static_cast<unsigned long long>(pi4_size / 1024));
		}

		if (defer)
			GSDeviceVK::GetInstance()->DeferImageDestruction(m_image, m_allocation);
		else
			vmaDestroyImage(GSDeviceVK::GetInstance()->GetAllocator(), m_image, m_allocation);
'''.replace("\\t", "\t").replace("\\n", "\n")
s = replace_once(s, old, new, "GSTextureVK destroy log")
tex.write_text(s)


# Instrument deferred Vulkan buffer/image destruction and cleanup execution.
dev = Path("pcsx2/GS/Renderers/Vulkan/GSDeviceVK.cpp")
s = dev.read_text()

s = replace_once(s, "#include <bit>\n", "#include <atomic>\n#include <bit>\n", "GSDeviceVK include")

anchor = "\n#ifdef ENABLE_OGL_DEBUG\n"
counters = """
static std::atomic<u64> s_pi4_defer_buffer_count{0};
static std::atomic<u64> s_pi4_free_buffer_count{0};
static std::atomic<u64> s_pi4_pending_buffer_count{0};
static std::atomic<u64> s_pi4_pending_buffer_bytes{0};
static std::atomic<u64> s_pi4_defer_image_count{0};
static std::atomic<u64> s_pi4_free_image_count{0};
static std::atomic<u64> s_pi4_pending_image_count{0};
static std::atomic<u64> s_pi4_pending_image_bytes{0};
"""
s = replace_once(s, anchor, "\n" + counters + anchor, "GSDeviceVK counters")

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
	if ((scheduled & 0xffu) == 0u)
	{
		Console.WriteLn("[PI4MEM] BUF_DEFER scheduled=%llu pending=%llu pending_kb=%llu last_kb=%llu",
			static_cast<unsigned long long>(scheduled), static_cast<unsigned long long>(pending_count),
			static_cast<unsigned long long>(pending_bytes / 1024), static_cast<unsigned long long>(bytes / 1024));
	}

	FrameResources& resources = m_frame_resources[m_current_frame];
	resources.cleanup_resources.push_back([this, object, allocation, bytes]() {
		vmaDestroyBuffer(m_allocator, object, allocation);
		const u64 freed = s_pi4_free_buffer_count.fetch_add(1, std::memory_order_relaxed) + 1;
		const u64 pending_after = s_pi4_pending_buffer_count.fetch_sub(1, std::memory_order_relaxed) - 1;
		const u64 bytes_after = s_pi4_pending_buffer_bytes.fetch_sub(bytes, std::memory_order_relaxed) - bytes;
		if ((freed & 0xffu) == 0u)
		{
			Console.WriteLn("[PI4MEM] BUF_FREE freed=%llu pending=%llu pending_kb=%llu",
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
	if ((scheduled & 0xffu) == 0u)
	{
		Console.WriteLn("[PI4MEM] IMG_DEFER scheduled=%llu pending=%llu pending_kb=%llu last_kb=%llu",
			static_cast<unsigned long long>(scheduled), static_cast<unsigned long long>(pending_count),
			static_cast<unsigned long long>(pending_bytes / 1024), static_cast<unsigned long long>(bytes / 1024));
	}

	FrameResources& resources = m_frame_resources[m_current_frame];
	resources.cleanup_resources.push_back([this, object, allocation, bytes]() {
		vmaDestroyImage(m_allocator, object, allocation);
		const u64 freed = s_pi4_free_image_count.fetch_add(1, std::memory_order_relaxed) + 1;
		const u64 pending_after = s_pi4_pending_image_count.fetch_sub(1, std::memory_order_relaxed) - 1;
		const u64 bytes_after = s_pi4_pending_image_bytes.fetch_sub(bytes, std::memory_order_relaxed) - bytes;
		if ((freed & 0xffu) == 0u)
		{
			Console.WriteLn("[PI4MEM] IMG_FREE freed=%llu pending=%llu pending_kb=%llu",
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

	if (resources.cleanup_resources.size() >= 128)
	{
		Console.WriteLn("[PI4MEM] CLEANUP frame=%u callbacks=%zu pending_img=%llu pending_img_kb=%llu pending_buf=%llu pending_buf_kb=%llu",
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
print("Pi4 Vulkan allocation tracing injected successfully")
