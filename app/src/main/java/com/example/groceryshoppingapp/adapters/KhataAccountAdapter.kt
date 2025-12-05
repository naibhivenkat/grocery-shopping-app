//package com.example.groceryshoppingapp.adapters
//
//import android.view.LayoutInflater
//import android.view.View
//import android.view.ViewGroup
//import androidx.core.content.ContextCompat
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.R
//import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
//import com.example.groceryshoppingapp.models.KhataAccount
//import com.example.groceryshoppingapp.utils.SessionManager
//import kotlin.math.abs
//
//class KhataAccountAdapter(
//    private val accounts: List<KhataAccount>,
//    private val onViewClick: (KhataAccount) -> Unit,
//    private val onPayClick: (KhataAccount) -> Unit
//) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {
//
//    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
//        RecyclerView.ViewHolder(binding.root) {
//
//        fun bind(acc: KhataAccount) {
//            val context = binding.root.context
//            val role = SessionManager.getRole(context)
//
//            // ✔ Name formatting
//            binding.tvName.text = if (role == "customer") {
//                acc.shopName ?: "Unknown Shop"
//            } else {
//                acc.customerName ?: "Unknown Customer"
//            }
//            binding.tvName.textSize = 18f
//            binding.tvName.setTypeface(binding.tvName.typeface, android.graphics.Typeface.BOLD_ITALIC)
//
//            binding.tvPhone.text = acc.phone?.let { "Phone: $it" } ?: "Phone: N/A"
//
//            val bal = acc.balance ?: 0.0
//            val absBal = abs(bal)
//
//            // ✔ Amount formatting
//            binding.tvBalance.textSize = 20f
//            binding.tvBalance.text = when (role) {
//                "customer" ->
//                    if (bal > 0) "₹-${String.format("%.2f", absBal)}"
//                    else if (bal < 0) "₹+${String.format("%.2f", absBal)}"
//                    else "₹0.00"
//
//                "shopowner" ->
//                    if (bal > 0) "₹+${String.format("%.2f", absBal)}"
//                    else if (bal < 0) "₹-${String.format("%.2f", absBal)}"
//                    else "₹0.00"
//
//                else -> "₹${String.format("%.2f", absBal)}"
//            }
//
//            // ✔ Color based on due/advance
//            if (role == "customer") {
//                if (bal > 0)
//                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_due_red))
//                else if (bal < 0)
//                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_advance_green))
//            } else {
//                if (bal > 0)
//                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_advance_green))
//                else if (bal < 0)
//                    binding.tvBalance.setTextColor(ContextCompat.getColor(context, R.color.khata_due_red))
//            }
//
//            // ✔ Badge
//            if (bal > 0) {
//                binding.tvStatusBadge.text = if (role == "customer") "DUE" else "RECEIVABLE"
//                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_due)
//            } else if (bal < 0) {
//                binding.tvStatusBadge.text = if (role == "customer") "ADVANCE" else "PAYABLE"
//                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_advance)
//            } else {
//                binding.tvStatusBadge.text = "CLEAR"
//            }
//
//            // 🔵 NEW → Show Pay Now button only for CUSTOMER + DUE AMOUNT
//            if (role == "customer" && bal > 0) {
//                binding.btnPayNow.visibility = View.VISIBLE
//                binding.btnPayNow.setOnClickListener { onPayClick(acc) }
//            } else {
//                binding.btnPayNow.visibility = View.GONE
//            }
//
//            // Existing click for open details
//            binding.root.setOnClickListener { onViewClick(acc) }
//
//        }
//    }
//
//    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
//        val binding = ItemKhataAccountBinding.inflate(
//            LayoutInflater.from(parent.context),
//            parent,
//            false
//        )
//        return ViewHolder(binding)
//    }
//
//    override fun getItemCount() = accounts.size
//
//    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
//        holder.bind(accounts[position])
//    }
//}
package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.utils.SessionManager
import kotlin.math.abs

class KhataAccountAdapter(
    private val accounts: List<KhataAccount>,
    private val onViewClick: (KhataAccount) -> Unit,
    private val onPayClick: (KhataAccount) -> Unit
) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(acc: KhataAccount) {
            val context = binding.root.context
            val role = SessionManager.getRole(context)

            binding.tvName.text = if (role == "customer") acc.shopName else acc.customerName
            binding.tvPhone.text = acc.phone ?: "Phone: N/A"

            val bal = acc.balance ?: 0.0
            val absBal = abs(bal)

            binding.tvBalance.text = "₹${String.format("%.2f", absBal)}"

            // ⭐ NEW — If pending cash exists, override badge
            if (acc.pendingStatus == "pending") {
                binding.tvStatusBadge.text = "PENDING CASH"
                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_yellow)
                binding.btnPayNow.visibility = View.GONE
            } else if (acc.pendingStatus == "approved") {
                binding.tvStatusBadge.text = "CASH APPROVED"
                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_green)
            } else if (acc.pendingStatus == "rejected") {
                binding.tvStatusBadge.text = "CASH REJECTED"
                binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_red)
            } else {
                // normal flow
                if (bal > 0) {
                    binding.tvStatusBadge.text = "DUE"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_badge_due)
                } else {
                    binding.tvStatusBadge.text = "CLEAR"
                }
            }

            // ⭐ Disable PayNow if cash is pending
            if (role == "customer" && bal > 0 && acc.pendingStatus != "pending") {
                binding.btnPayNow.visibility = View.VISIBLE
                binding.btnPayNow.setOnClickListener { onPayClick(acc) }
            } else {
                binding.btnPayNow.visibility = View.GONE
            }

            binding.root.setOnClickListener { onViewClick(acc) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val b = ItemKhataAccountBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return ViewHolder(b)
    }

    override fun getItemCount() = accounts.size
    override fun onBindViewHolder(h: ViewHolder, pos: Int) = h.bind(accounts[pos])
}
