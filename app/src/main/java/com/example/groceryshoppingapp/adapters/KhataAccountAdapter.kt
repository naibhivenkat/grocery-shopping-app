//package com.example.groceryshoppingapp.adapters
//
//import android.view.LayoutInflater
//import android.view.ViewGroup
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.R
//import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
//import com.example.groceryshoppingapp.models.KhataAccount
//import com.example.groceryshoppingapp.utils.SessionManager
//
//class KhataAccountAdapter(
//    private val accounts: List<KhataAccount>,
//    private val clickListener: (KhataAccount) -> Unit
//) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {
//
//    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
//        RecyclerView.ViewHolder(binding.root) {
//
//        fun bind(acc: KhataAccount) {
//
//            val role = SessionManager.getRole(binding.root.context)
//
//            // CUSTOMER APP → show shop name
//            // SHOP OWNER → show customer name
//            binding.tvName.text = if (role == "customer") {
//                acc.shopName ?: "Unknown Shop"
//            } else {
//                acc.customerName ?: "Unknown Customer"
//            }
//
//            binding.tvPhone.text = acc.phone?.let { "Phone: $it" } ?: "Phone: N/A"
//
//            val bal = acc.balance ?: 0.0
//            binding.tvBalance.text = "₹${String.format("%.2f", bal)}"
//
//            when {
//                bal > 0 -> {
//                    binding.tvStatusBadge.text = "DUE"
//                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_due)
//                }
//                bal < 0 -> {
//                    binding.tvStatusBadge.text = "ADVANCE"
//                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
//                }
//                else -> {
//                    binding.tvStatusBadge.text = "CLEAR"
//                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
//                }
//            }
//
//            binding.root.setOnClickListener { clickListener(acc) }
//        }
//
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

//package com.example.groceryshoppingapp.adapters
//
//import android.view.LayoutInflater
//import android.view.ViewGroup
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.R
//import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
//import com.example.groceryshoppingapp.models.KhataAccount
//import com.example.groceryshoppingapp.utils.SessionManager
//
//class KhataAccountAdapter(
//    private val accounts: List<KhataAccount>,
//    private val clickListener: (KhataAccount) -> Unit
//) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {
//
//    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
//        RecyclerView.ViewHolder(binding.root) {
//
//        fun bind(acc: KhataAccount) {
//
//            val role = SessionManager.getRole(binding.root.context)
//
//            // CUSTOMER → shop name
//            // SHOP OWNER → customer name
//            binding.tvName.text = if (role == "customer") {
//                acc.shopName ?: "Unknown Shop"
//            } else {
//                acc.customerName ?: "Unknown Customer"
//            }
//
//            binding.tvPhone.text = acc.phone?.let { "Phone: $it" } ?: "Phone: N/A"
//
//            val balance = acc.balance ?: 0.0
//            val absBal = kotlin.math.abs(balance)
//
//            // ⭐ FIX → Always show POSITIVE number for display (customer-friendly)
//            binding.tvBalance.text = "₹${String.format("%.2f", absBal)}"
//
//            // ⭐ FIX → Correct badges for both sides
//            when {
//                balance > 0 -> { // customer owes shop
//                    binding.tvStatusBadge.text = "DUE"
//                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_due)
//                }
//                balance < 0 -> { // shop owes customer
//                    binding.tvStatusBadge.text = "ADVANCE"
//                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
//                }
//                else -> {
//                    binding.tvStatusBadge.text = "CLEAR"
//                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
//                }
//            }
//
//            binding.root.setOnClickListener { clickListener(acc) }
//        }
//
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

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataAccountBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.utils.SessionManager

class KhataAccountAdapter(
    private val accounts: List<KhataAccount>,
    private val clickListener: (KhataAccount) -> Unit
) : RecyclerView.Adapter<KhataAccountAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataAccountBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(acc: KhataAccount) {

            val role = SessionManager.getRole(binding.root.context)

            // CUSTOMER sees SHOP name
            // SHOP OWNER sees CUSTOMER name
            binding.tvName.text = if (role == "customer") {
                acc.shopName ?: "Unknown Shop"
            } else {
                acc.customerName ?: "Unknown Customer"
            }

            val bal = acc.balance ?: 0.0
            val abs = kotlin.math.abs(bal)

            binding.tvPhone.text = acc.phone ?: "-"

            // Display + or –
            binding.tvBalance.text = if (role == "customer") {
                if (bal > 0) "₹-${String.format("%.2f", abs)}"
                else "₹+${String.format("%.2f", abs)}"
            } else {
                if (bal > 0) "₹+${String.format("%.2f", abs)}"
                else "₹-${String.format("%.2f", abs)}"
            }

            // Color logic
            if (role == "customer") {
                // Customer POV
                binding.tvBalance.setTextColor(
                    if (bal > 0) Color.RED else Color.parseColor("#4CAF50")
                )
            } else {
                // Shop Owner POV
                binding.tvBalance.setTextColor(
                    if (bal > 0) Color.parseColor("#4CAF50") else Color.RED
                )
            }

            // Badge
            when {
                bal > 0 -> {
                    binding.tvStatusBadge.text = if (role == "customer") "DUE" else "RECEIVABLE"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_due)
                }
                bal < 0 -> {
                    binding.tvStatusBadge.text = if (role == "customer") "ADVANCE" else "PAYABLE"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
                else -> {
                    binding.tvStatusBadge.text = "CLEAR"
                    binding.tvStatusBadge.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
            }

            binding.root.setOnClickListener { clickListener(acc) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemKhataAccountBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return ViewHolder(binding)
    }

    override fun getItemCount() = accounts.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(accounts[position])
    }
}
